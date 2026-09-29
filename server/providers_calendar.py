#!/usr/bin/env python3
"""The owner's next events, from Google Calendar and Microsoft Outlook.

ADR 0017 is the decision. This module turns two providers that disagree
about almost everything into one short list the panel can render, and it
drops what the panel has no business receiving on the way.

    Google     GET calendar/v3/calendars/primary/events
               ?timeMin&timeMax&singleEvents=true&orderBy=startTime
               timed events carry start.dateTime (RFC 3339 with offset),
               all-day ones carry start.date; "you said no" is
               attendees[self=true].responseStatus == "declined"
    Microsoft  GET graph v1.0 /me/calendar/calendarView
               ?startDateTime&endDateTime, Prefer: outlook.timezone="UTC"
               dateTime has no offset and seven fractional digits; "you said
               no" is responseStatus.response == "declined"

**Only the primary calendar, and only reads.** Every call here is a GET, and
a guard test fails the build if one is not (ADR 0017).

**Filtering happens here, not on the phone.** A declined or cancelled event
never leaves the PC, so it is never on the LAN at all. What does leave is
`{start, end, allDay, source, title?}` and nothing more: no attendees, no
location, no body, no link, no id.

**Ask for one more than you need.** Both providers are asked for
`FETCH_PER_ACCOUNT` events. An all-day event and a declined one are filtered
after the fetch, and a window that returned exactly what was wanted can
return none that survive.
"""
import datetime
import re
import sys
import urllib.parse

from server.oauth import OAuthError
from server.upstream import UpstreamError, get_json

GOOGLE_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GRAPH_CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendar/calendarView"

PROVIDERS = ("google", "microsoft")

# How many of each kind reach the panel. The page shows one; the rest are
# there so the page can move on to the next event the moment one ends,
# without waiting a whole `calendar_interval_s` for the server.
MAX_TIMED = 3
MAX_ALL_DAY = 2
FETCH_PER_ACCOUNT = 5

# A title longer than this is cut on the server. The card is one line, and a
# pasted meeting description in a title field is data nobody asked to put on
# the LAN.
MAX_TITLE = 80

# Google event types that are not meetings. A working-location entry is a
# note about where the owner is, and shown as "the next event" it would hide
# the real one behind it every morning.
SKIPPED_GOOGLE_TYPES = {"workingLocation"}

ACCOUNT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def accounts_from_config(value):
    """Pure: `calendar_accounts` -> `[(provider, name), ...]`, or ValueError.

    Checked at startup, like `actions` (ADR 0015): a typo in a provider name
    has to be found by the person restarting the server, not by someone
    waiting for a meeting that never appears. The name becomes part of a
    log line and of the payload's `source`, so it is held to a shape that
    cannot carry anything else.
    """
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise ValueError("calendar_accounts must be a list of {provider, name} tables")
    accounts = []
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("calendar_accounts: each entry must be {provider = ..., name = ...}")
        provider = entry.get("provider")
        name = entry.get("name")
        if provider not in PROVIDERS:
            raise ValueError(
                f"calendar_accounts: unknown provider {provider!r}; "
                f"expected one of {', '.join(PROVIDERS)}")
        if not isinstance(name, str) or not ACCOUNT_NAME.match(name):
            raise ValueError(
                f"calendar_accounts: name {name!r} must be lowercase letters, digits "
                f"and hyphens, at most 32")
        account = f"{provider}/{name}"
        if account in seen:
            raise ValueError(f"calendar_accounts: {account} is listed twice")
        seen.add(account)
        accounts.append((provider, name))
    return accounts


def missing_client_ids(accounts, config):
    """Pure: which providers in use have no client id configured."""
    keys = {"google": "google_client_id", "microsoft": "microsoft_client_id"}
    return sorted({keys[provider] for provider, _ in accounts
                   if not str(config.get(keys[provider], "")).strip()})


def _rfc3339(instant):
    return instant.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_google(access_token, time_min, time_max, get=get_json):
    """events.list on the primary calendar. The seam the tests patch.

    `timeMin` bounds the event's *end*, so an event already in progress is
    included, which is what the panel wants. `fields` asks for exactly what
    `normalise_google` reads, so nothing else crosses the wire either.
    """
    query = urllib.parse.urlencode({
        "timeMin": _rfc3339(time_min),
        "timeMax": _rfc3339(time_max),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(FETCH_PER_ACCOUNT),
        "fields": "items(status,summary,eventType,start,end,attendees(self,responseStatus))",
    })
    return get(f"{GOOGLE_EVENTS_URL}?{query}",
               headers={"Authorization": f"Bearer {access_token}"})


def fetch_graph(access_token, start, end, get=get_json):
    """calendarView on the default calendar. The seam the tests patch.

    `Prefer: outlook.timezone="UTC"` because otherwise the zone comes back
    as a Windows name ("E. South America Standard Time") that the standard
    library cannot resolve. In UTC every instant is exact, and the all-day
    case is handled in `normalise_graph`.
    """
    query = urllib.parse.urlencode({
        "startDateTime": _rfc3339(start),
        "endDateTime": _rfc3339(end),
        "$select": "subject,start,end,isAllDay,isCancelled,responseStatus",
        "$orderby": "start/dateTime",
        "$top": str(FETCH_PER_ACCOUNT),
    })
    return get(f"{GRAPH_CALENDAR_VIEW_URL}?{query}",
               headers={"Authorization": f"Bearer {access_token}",
                        "Prefer": 'outlook.timezone="UTC"'})


def _title(text):
    if not isinstance(text, str):
        return None
    text = " ".join(_CONTROL.sub(" ", text).split())
    if not text:
        return None
    return text if len(text) <= MAX_TITLE else text[:MAX_TITLE - 1].rstrip() + "…"


def _parse_instant(text):
    """An RFC 3339 string -> an aware datetime, or None."""
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _parse_date(text):
    if not isinstance(text, str):
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def normalise_google(raw, source):
    """Pure: an events.list body -> `[event, ...]`, filtered."""
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return []
    events = []
    for item in raw["items"]:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "cancelled":
            continue
        if item.get("eventType") in SKIPPED_GOOGLE_TYPES:
            continue
        attendees = item.get("attendees") if isinstance(item.get("attendees"), list) else []
        if any(isinstance(a, dict) and a.get("self") and a.get("responseStatus") == "declined"
               for a in attendees):
            continue
        start = item.get("start") if isinstance(item.get("start"), dict) else {}
        end = item.get("end") if isinstance(item.get("end"), dict) else {}
        event = _event(start.get("dateTime"), end.get("dateTime"),
                       start.get("date"), end.get("date"), source, item.get("summary"))
        if event:
            events.append(event)
    return events


def _graph_instant(value):
    """Graph's `{dateTime, timeZone}` in UTC -> an aware datetime, or None.

    The fraction is seven digits, `2026-09-29T17:00:00.0000000`, and
    `fromisoformat` accepts at most six, so it is dropped: no calendar is
    precise to the microsecond.
    """
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        return None
    if str(value.get("timeZone", "UTC")).upper() not in ("UTC", "ETC/UTC"):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value["dateTime"].split(".", 1)[0])
    except ValueError:
        return None
    return parsed.replace(tzinfo=datetime.timezone.utc)


def _nearest_date(instant):
    """The calendar date whose midnight is nearest to `instant`.

    An all-day event in Graph is midnight to midnight *in the event's own
    zone*, and asking for UTC moves that midnight: 00:00 in São Paulo is
    03:00Z, 00:00 in Tokyo is 15:00Z the day before. Midnight anywhere
    between UTC-12 and UTC+12 lies within twelve hours of the UTC midnight of
    the same date, so rounding to the nearest one recovers the date. Only
    UTC+13 and +14, a few Pacific islands, are outside that.
    """
    return (instant + datetime.timedelta(hours=12)).date()


def normalise_graph(raw, source):
    """Pure: a calendarView body -> `[event, ...]`, filtered."""
    if not isinstance(raw, dict) or not isinstance(raw.get("value"), list):
        return []
    events = []
    for item in raw["value"]:
        if not isinstance(item, dict):
            continue
        if item.get("isCancelled") is True:
            continue
        status = item.get("responseStatus") if isinstance(item.get("responseStatus"), dict) else {}
        if status.get("response") == "declined":
            continue
        start = _graph_instant(item.get("start"))
        end = _graph_instant(item.get("end"))
        if start is None or end is None:
            continue
        if item.get("isAllDay") is True:
            event = _event(None, None, _nearest_date(start).isoformat(),
                           _nearest_date(end).isoformat(), source, item.get("subject"))
        else:
            event = _event(start.isoformat(), end.isoformat(), None, None,
                           source, item.get("subject"))
        if event:
            events.append(event)
    return events


def _event(start_time, end_time, start_date, end_date, source, title):
    """Pure: the one shape both providers are turned into, or None if unusable."""
    if start_time is not None:
        start, end = _parse_instant(start_time), _parse_instant(end_time)
        if start is None or end is None or end <= start:
            return None
        event = {"start": start.isoformat(), "end": end.isoformat(), "allDay": False}
    else:
        start, end = _parse_date(start_date), _parse_date(end_date)
        if start is None or end is None or end <= start:
            return None
        event = {"start": start.isoformat(), "end": end.isoformat(), "allDay": True}
    event["source"] = source
    title = _title(title)
    if title:
        event["title"] = title
    return event


def _sort_key(event):
    """Timed events by instant; all-day events by date, as a UTC midnight.

    The order only decides which few are sent, not which one the panel
    shows. That choice is the page's, against the phone's own clock.
    """
    if event["allDay"]:
        instant = datetime.datetime.fromisoformat(event["start"]).replace(
            tzinfo=datetime.timezone.utc)
    else:
        instant = datetime.datetime.fromisoformat(event["start"])
    return (instant, event["source"], event.get("title", ""))


def select(events, show_titles):
    """Pure: the merged list -> at most MAX_TIMED timed and MAX_ALL_DAY all-day.

    Kept apart rather than cut together, because three all-day events
    (a holiday, a birthday, a trip) would otherwise push out the one meeting
    that has a time on it. `show_titles = false` drops every title here, on
    the server, before the payload exists (ADR 0017).
    """
    ordered = sorted(events, key=_sort_key)
    timed = [e for e in ordered if not e["allDay"]][:MAX_TIMED]
    all_day = [e for e in ordered if e["allDay"]][:MAX_ALL_DAY]
    chosen = sorted(timed + all_day, key=_sort_key)
    if not show_titles:
        chosen = [{k: v for k, v in e.items() if k != "title"} for e in chosen]
    return chosen


def load(accounts, credentials, now, lookahead_h, show_titles,
         google=None, graph=None, log=None):
    """`{accounts, events, failed}` for every configured account.

    **Never raises, and never serves a stale value.** An account that fails
    costs its own events and is named in `failed`; the others still answer.
    That is the opposite of what the market caches do, on purpose: an old
    price is still useful, and an old meeting may be one already missed
    (T9.1 notes). The log line names the account and the reason, never a
    token or a title.
    """
    # Resolved here rather than as defaults, so a test patching the module's
    # fetch seam reaches this call too.
    google = google or fetch_google
    graph = graph or fetch_graph
    log = log or (lambda line: print(line, file=sys.stderr))
    until = now + datetime.timedelta(hours=lookahead_h)
    events, failed = [], []
    for provider, name in accounts:
        source = f"{provider}/{name}"
        try:
            token = credentials[source].access_token()
            if provider == "google":
                rows = normalise_google(google(token, now, until), source)
            else:
                rows = normalise_graph(graph(token, now, until), source)
        except (OAuthError, UpstreamError) as exc:
            failed.append(source)
            log(f"calendar {source}: {exc}")
            continue
        events.extend(rows)
    return {"accounts": len(accounts),
            "events": select(events, show_titles),
            "failed": failed}
