#!/usr/bin/env python3
"""The moon's phase, from the US Naval Observatory.

No API key, no terms to accept, and it is the authority rather than a
convenience: the USNO's Astronomical Applications department is what almanacs
are checked against. Asked for because a computed phase is *approximately*
right and the one thing a panel cannot be approximately right about is a shape
somebody can compare with the sky by looking up.

Shape below is measured, 2026-09-21, not read off the docs.

    GET aa.usno.navy.mil/api/moon/phases/date?date=2026-09-01&nump=8
    {"apiversion": "4.0.1", "numphases": 8, "phasedata": [
        {"day": 4, "month": 9, "phase": "Last Quarter", "time": "07:51",
         "year": 2026},
        {"day": 11, "month": 9, "phase": "New Moon", "time": "03:27",
         "year": 2026}, ...]}

Times are UTC. The `date` endpoint rather than `year`, because what this needs
is a window that *brackets* now with a New Moon on each side: a year table is
one request but needs a second one every January to answer a question about the
3rd. Nine phases from five weeks back span about 66 days, 35 behind and 31
ahead, which brackets whatever the month boundary is doing. The first cut asked
for six from 45 days back, which spans 44 -- so the window could end before
today and `phase_at` refused to answer. The fixture test caught it.

**The phase is derived here, not read off.** The API gives the *instants* of
the four primary phases; the panel needs "what does it look like tonight",
which is where now falls between two New Moons. Deriving it from the real
lunation is the whole point: a lunation is 29.27 to 29.83 days long and the
mean-synodic shortcut in `web/js/format.js` is up to 0.9 of a day out, which
is a visibly different moon on the nights either side of a quarter.

`moon_phase` is what the payload carries and it is a name plus a lit fraction
-- never a picture. `format.js` owns the eight names' wording and the theme
owns what a moon looks like, the same split the WMO codes get.
"""
import datetime

from server.upstream import UpstreamError, get_json

PHASES_URL = "https://aa.usno.navy.mil/api/moon/phases/date"

# The window has to *bracket* now with a New Moon on each side, and the first
# cut of these two numbers did not: six phases from 45 days back span about 44
# days, so the last of them can fall before today and `phase_at` correctly
# refuses to answer. Caught by the fixture test rather than by reading.
#
# Five weeks back and nine phases spans about 66 days -- 35 behind and 31
# ahead -- so there is a New Moon on each side of now whatever the month
# boundary is doing. One request either way.
LOOKBACK_DAYS = 35
NUMP = 9

# The eight names, in the order a lunation visits them. `format.js` has the
# same list and the same order; a test asserts the two agree, because the panel
# would otherwise draw a waxing crescent and call it waning.
PHASE_NAMES = (
    "new",
    "waxing-crescent",
    "first-quarter",
    "waxing-gibbous",
    "full",
    "waning-gibbous",
    "last-quarter",
    "waning-crescent",
)

# What the USNO calls the four it reports.
PRIMARY = {
    "New Moon": "new",
    "First Quarter": "first-quarter",
    "Full Moon": "full",
    "Last Quarter": "last-quarter",
}


def fetch_phases(when=None, get=get_json):
    """The primary phases around `when` (UTC), as the API returns them."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    start = (when - datetime.timedelta(days=LOOKBACK_DAYS)).date()
    return get("%s?date=%s&nump=%d" % (PHASES_URL, start.isoformat(), NUMP))


def normalise_phases(raw):
    """The response -> a sorted list of `{"when": datetime, "phase": name}`.

    Anything unparsable is dropped rather than raising: a table missing one of
    six entries still brackets now, and a partial answer is worth more than an
    exception on a panel whose other four cards are fine.
    """
    if not isinstance(raw, dict):
        return []
    out = []
    for item in raw.get("phasedata") or []:
        if not isinstance(item, dict):
            continue
        name = PRIMARY.get(item.get("phase"))
        if name is None:
            continue
        try:
            hour, minute = str(item["time"]).split(":")[:2]
            out.append({
                "when": datetime.datetime(
                    int(item["year"]), int(item["month"]), int(item["day"]),
                    int(hour), int(minute), tzinfo=datetime.timezone.utc),
                "phase": name,
            })
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda p: p["when"])
    return out


def phase_at(phases, when=None):
    """`{phase, illum, ageDays, lunationDays, source}` or None.

    None when the table does not bracket `when` with two New Moons, which is
    the only honest answer available: without both ends there is no lunation to
    take a fraction of, and guessing its length is the approximation this
    module exists to avoid. The caller falls back rather than being handed a
    number with no provenance.
    """
    when = when or datetime.datetime.now(datetime.timezone.utc)
    news = [p["when"] for p in phases if p["phase"] == "new"]
    before = [t for t in news if t <= when]
    after = [t for t in news if t > when]
    if not before or not after:
        return None
    start, end = max(before), min(after)
    lunation = (end - start).total_seconds()
    if lunation <= 0:
        return None
    age = (when - start).total_seconds()
    return _describe(age / 86400.0, lunation / 86400.0, "usno")


def _describe(age_days, lunation_days, source):
    """Age within a lunation -> the name and the lit fraction.

    Eight buckets **centred** on the phases, not starting at them: the day of
    the full moon has to be `full` rather than `waxing-gibbous` until the
    instant it passes. That is the `+ 0.5` before the floor, and it is the one
    piece of arithmetic here worth stating twice.
    """
    import math

    fraction = (age_days / lunation_days) % 1.0
    index = int(math.floor(fraction * 8 + 0.5)) % 8
    return {
        "phase": PHASE_NAMES[index],
        # The illuminated fraction as a percentage of the disc, rounded to a
        # whole number: the panel draws a shape from it and nobody reads a
        # decimal off a moon.
        "illum": int(round((1 - math.cos(2 * math.pi * fraction)) / 2 * 100)),
        "ageDays": round(age_days, 2),
        "lunationDays": round(lunation_days, 3),
        "source": source,
    }


# The mean synodic month, for the fallback below. Not a measurement of any
# particular lunation -- that is the point of the difference.
SYNODIC_DAYS = 29.530588853

# A New Moon that every published table agrees on, as the anchor: 2000-01-06
# 18:14 UTC. Checked against the USNO's own 2026 and 2027 tables before being
# written down here -- 99 primary phases, every one named correctly, worst
# error 0.87 days against a bucket half-width of 1.85.
SYNODIC_ANCHOR = datetime.datetime(2000, 1, 6, 18, 14,
                                   tzinfo=datetime.timezone.utc)


def synodic_phase(when=None):
    """The same shape, from arithmetic, for when the network is not there.

    Marked `source: "mean"` so the panel can say so and so a reader of a
    payload is never left guessing which of the two answered. It names the
    phase correctly -- that was measured -- and its age can be most of a day
    out, which is why it is the fallback and not the plan.
    """
    when = when or datetime.datetime.now(datetime.timezone.utc)
    age = ((when - SYNODIC_ANCHOR).total_seconds() / 86400.0) % SYNODIC_DAYS
    return _describe(age, SYNODIC_DAYS, "mean")


def moon_phase(when=None, get=get_json):
    """The panel's answer: the USNO's lunation when it can be had, else mean.

    Never raises. A moon is the least important thing on this panel and the
    weather card has to draw regardless -- the same rule every other provider
    here follows.
    """
    when = when or datetime.datetime.now(datetime.timezone.utc)
    try:
        answer = phase_at(normalise_phases(fetch_phases(when, get=get)), when)
    except (UpstreamError, ValueError, TypeError):
        answer = None
    return answer or synodic_phase(when)


if __name__ == "__main__":
    import json
    print(json.dumps(moon_phase(), indent=2))
