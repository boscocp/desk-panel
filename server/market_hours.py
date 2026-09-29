"""When B3 can have a new price, so brapi is not asked when it cannot.

brapi's free plan is 15,000 requests a month, and the quote cache used to
spend them around the clock: a price asked for at 03:00 on a Sunday is
Friday's close, fetched again every `quotes_interval_s` until Monday.
Outside the window below the server keeps serving the rows it already holds
and asks for nothing.

The window, checked 2026-09-29 against B3's announcements and brapi's FAQ:

- B3 opens at 10:00 all year, and moves its close twice a year to follow
  **US** daylight saving, because of the foreign volume. While the US is on
  summer time (second Sunday of March to first Sunday of November) the
  closing call ends at 17:00; the rest of the year it ends at 18:00. B3
  switches on the Monday after the US does, which is what comparing
  calendar dates in Sao Paulo gives for free.
- brapi's free plan serves stock quotes about 30 minutes late, so the close
  reaches it around 17:30 or 18:30. `DELAY_MARGIN_MIN` covers that with a
  quarter of an hour to spare.

Holidays are not modelled: a holiday costs one ordinary weekday's requests,
and a holiday calendar that drifted would cost a day of prices.

The clock is fixed at UTC-3, not read from `config.timezone`. The window is
the exchange's, and the exchange is in Sao Paulo whatever city the panel
shows. Brazil has had no daylight saving of its own since 2019; if it ever
comes back, this offset is the line to change. A fixed offset and the US
rule as arithmetic need no tz database, which Windows does not ship and the
standard library does not bring (`zoneinfo` would want `tzdata`).
"""
import datetime

B3_TZ = datetime.timezone(datetime.timedelta(hours=-3), "BRT")

OPEN_MIN = 10 * 60
CLOSE_US_SUMMER_MIN = 17 * 60
CLOSE_US_WINTER_MIN = 18 * 60
DELAY_MARGIN_MIN = 45

DEFAULT_HOURS = "auto"


def _nth_sunday(year, month, n):
    """Pure: the date of the n-th Sunday of a month."""
    first = datetime.date(year, month, 1)
    return first + datetime.timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def us_summer_time(day):
    """Pure: whether the US is on daylight saving on this calendar date.

    The Energy Policy Act of 2005 rule, in force since 2007: from the second
    Sunday of March to the first Sunday of November.
    """
    return _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)


def auto_window(day, margin=DELAY_MARGIN_MIN):
    """Pure: B3's `(open, close)` for a date, in minutes, plus `margin`.

    The margin is brapi's delay, for deciding whether to ask it. With
    `margin=0` it is the exchange's own session, for saying whether the
    market is open -- which is what the panel's label says.
    """
    close = CLOSE_US_SUMMER_MIN if us_summer_time(day) else CLOSE_US_WINTER_MIN
    return OPEN_MIN, close + margin


def _minutes(text, name):
    """Pure: "HH:MM" -> minutes past midnight. "24:00" is the end of the day."""
    if not isinstance(text, str) or len(text) != 5 or text[2] != ":":
        raise ValueError(f"b3_hours: {name} must be \"HH:MM\", not {text!r}")
    hours, minutes = text[:2], text[3:]
    if not (hours.isdigit() and minutes.isdigit()):
        raise ValueError(f"b3_hours: {name} must be \"HH:MM\", not {text!r}")
    value = int(hours) * 60 + int(minutes)
    if int(minutes) > 59 or value > 24 * 60:
        raise ValueError(f"b3_hours: {name} is not a time of day: {text!r}")
    return value


def hours_from_config(config):
    """Pure: the config -> "auto", a fixed `(open, close)`, or None for "always".

    `"auto"` follows B3's two seasons. Two times fix the window all year, for
    somebody who wants the after-market or a paid plan's shorter delay. An
    empty list switches the gate off. Anything else raises ValueError, which
    startup and `--check-only` turn into a message and an exit.
    """
    hours = config.get("b3_hours", DEFAULT_HOURS)
    if hours == "auto":
        return "auto"
    if isinstance(hours, list) and not hours:
        return None
    if not isinstance(hours, list) or len(hours) != 2:
        raise ValueError(
            f"b3_hours must be \"auto\", [\"HH:MM\", \"HH:MM\"] or [], not {hours!r}")
    start, end = _minutes(hours[0], "the opening"), _minutes(hours[1], "the close")
    if start >= end:
        raise ValueError(f"b3_hours must open before it closes, not {hours!r}")
    return start, end


def is_open(when, hours):
    """Pure: whether B3 can have a price at `when` that brapi did not have before.

    `when` is an aware datetime in any zone. `hours` is what
    `hours_from_config` returned; None means the gate is off and every
    instant counts as open.
    """
    if hours is None:
        return True
    local = when.astimezone(B3_TZ)
    if local.weekday() >= 5:
        return False
    start, end = auto_window(local.date()) if hours == "auto" else hours
    minute = local.hour * 60 + local.minute
    return start <= minute < end


def exchange_open(when):
    """Pure: whether B3's session is running at `when`, by the exchange's clock.

    Not `is_open`: that one keeps asking brapi for 45 minutes after the close
    and can be configured away, and neither is true of the market itself.
    This is what the panel's CLOSED label reads.
    """
    local = when.astimezone(B3_TZ)
    if local.weekday() >= 5:
        return False
    start, end = auto_window(local.date(), margin=0)
    minute = local.hour * 60 + local.minute
    return start <= minute < end
