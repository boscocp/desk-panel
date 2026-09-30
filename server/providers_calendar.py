#!/usr/bin/env python3
"""The owner's next events, from Google Calendar and Microsoft Outlook.

ADR 0017 is the decision. This module turns two providers that disagree
about almost everything into one short list the panel can render, and it
drops what the panel has no business receiving on the way.

    Google     GET calendar/v3/users/me/calendarList, then for each calendar
               the owner shows: GET calendar/v3/calendars/{id}/events
               ?timeMin&timeMax&singleEvents=true&orderBy=startTime
               timed events carry start.dateTime (RFC 3339 with offset),
               all-day ones carry start.date; "you said no" is
               attendees[self=true].responseStatus == "declined"
    Microsoft  GET graph v1.0 /me/calendar/calendarView
               ?startDateTime&endDateTime, Prefer: outlook.timezone="UTC"
               dateTime has no offset and seven fractional digits; "you said
               no" is responseStatus.response == "declined"

**Only reads.** Every call here is a GET, and a guard test fails the build if
one is not (ADR 0017). Google reads every calendar the owner has switched on
in Google Calendar, shared and subscribed ones included (ADR 0019); Outlook
reads the default calendar.

**Filtering happens here, not on the phone.** A declined or cancelled event
never leaves the PC, so it is never on the LAN at all. What does leave is
`{start, end, allDay, source, title?}` and nothing more: no attendees, no
location, no body, no link, no id.

**Ask for far more than you need.** The panel is sent at most five events,
and each provider is asked for `FETCH_PER_ACCOUNT` per page, over up to
`MAX_PAGES` pages. Declined, cancelled and working-location entries are
filtered after the fetch, and on a busy morning they can fill a small page
before the first meeting that survives. A page can also come back short, or
empty, with more to follow (events.list: "Incomplete pages can be detected by
a non-empty nextPageToken field"), so the next page is followed rather than
the answer taken as final.
"""
import datetime
import re
import sys
import time
import unicodedata
import urllib.parse

from server.oauth import AUTH_ERRORS, OAuthError
from server.upstream import UpstreamError, get_json

GOOGLE_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{}/events"
GOOGLE_CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"

# How many of the owner's calendars are read, the primary included. Each is at
# least one request every `calendar_interval_s`, off the request path; ten is
# far more than a person switches on, and a cap on something the owner does
# not control (who shares a calendar with them) is cheap to have.
MAX_CALENDARS = 10

# How long one Google account may spend reading its calendars, in seconds.
# Sequentially, ten calendars of three pages each at a ten-second timeout is
# over five minutes -- longer than `calendar_interval_s` -- and a slow shared
# calendar would hold up every account after it in the same refresh. Past the
# budget the remaining calendars are skipped, and the log says how many.
GOOGLE_BUDGET_S = 60
GRAPH_CALENDAR_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendar/calendarView"

PROVIDERS = ("google", "microsoft")

# How many of each kind reach the panel. The page shows one; the rest are
# there so the page can move on to the next event the moment one ends,
# without waiting a whole `calendar_interval_s` for the server.
MAX_TIMED = 3
MAX_ALL_DAY = 2
FETCH_PER_ACCOUNT = 25
MAX_PAGES = 3

# A title longer than this is cut on the server. The card is one line, and a
# pasted meeting description in a title field is data nobody asked to put on
# the LAN.
MAX_TITLE = 80

# Google event types that are meetings, asked for by name so the others never
# cross the wire. A working-location entry is a note about where the owner is;
# focus time and out-of-office are blocks the owner drew around their own day;
# a birthday is a contact's. Shown as "the next event", each would hide the
# real one behind it.
GOOGLE_EVENT_TYPES = ("default", "fromGmail")
SKIPPED_GOOGLE_TYPES = {"workingLocation", "focusTime", "outOfOffice", "birthday"}

# The labels Graph may put on an instant that is UTC. Asked for as "UTC", and
# the echo is not documented, so the spellings of UTC are all accepted and
# anything else fails the account out loud rather than dropping its events.
UTC_LABELS = {"UTC", "ETC/UTC", "ETC/GMT", "GMT", "COORDINATED UNIVERSAL TIME",
              "TZONE://MICROSOFT/UTC"}

ACCOUNT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")

# Why an account failed, for the card. `reconnect` is the owner's job:
# `calendar_login.py` fixes it. `unavailable` is the provider's, and the next
# cycle retries by itself.
RECONNECT = "reconnect"
UNAVAILABLE = "unavailable"


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
        if not isinstance(name, str) or not ACCOUNT_NAME.fullmatch(name):
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
    """Pure: which of the client keys the accounts in use need are not set.

    Google needs its secret as well as its id, because the refresh sends
    both, and a config missing it would pass `--check-only` and then fail
    every cycle with `invalid_client`.
    """
    keys = {"google": ("google_client_id", "google_client_secret"),
            "microsoft": ("microsoft_client_id",)}
    needed = {key for provider, _ in accounts for key in keys[provider]}
    return sorted(key for key in needed
                  if not (isinstance(config.get(key), str) and config[key].strip()))


def check_config(config):
    """Pure: raise ValueError unless the calendar keys have the types they must.

    Checked at startup, beside `calendar_accounts`, because each of these
    fails badly at run time. `bool("false")` is True, so a quoted `"false"`
    in `calendar_show_titles` would publish the titles the owner turned off.
    A string interval raises inside `/quotes` and takes every card with it.
    And a string `allowed_hosts` is iterated a character at a time.
    """
    titles = config.get("calendar_show_titles", True)
    if not isinstance(titles, bool):
        raise ValueError(f"calendar_show_titles must be true or false, not {titles!r}")
    interval = config.get("calendar_interval_s", 300)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 60:
        raise ValueError(f"calendar_interval_s must be a whole number of seconds, at least 60, "
                         f"not {interval!r}")
    lookahead = config.get("calendar_lookahead_h", 24)
    if isinstance(lookahead, bool) or not isinstance(lookahead, (int, float)) \
            or not 0 < lookahead <= 24 * 14:
        raise ValueError(f"calendar_lookahead_h must be a number of hours from 1 to 336, "
                         f"not {lookahead!r}")
    hosts = config.get("allowed_hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) and h.strip() for h in hosts):
        raise ValueError(f"allowed_hosts must be a list of names, e.g. [\"mypc.local\"], "
                         f"not {hosts!r}")


def _rfc3339(instant):
    return instant.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_google_calendars(access_token, get=get_json, log=None):
    """The ids of the calendars to read: the primary, then every other one the
    owner has switched on in Google Calendar, up to MAX_CALENDARS.

    `selected` is the checkbox beside a calendar in Google Calendar's own list
    (calendarList: "Whether the calendar content shows up in the calendar UI.
    ... The default is False"), so the panel shows what the owner already
    chose to look at, and a calendar they unticked stays off it. Only a real
    `true` counts. Hidden ones are not listed at all without `showHidden`.
    The primary is always read, whatever it says, as it was before ADR 0019.
    """
    log = log or _stderr
    params = [("minAccessRole", "reader"), ("maxResults", "250"),
              ("fields", "items(id,primary,selected),nextPageToken")]
    headers = {"Authorization": f"Bearer {access_token}"}
    ids, token = ["primary"], None
    for _ in range(MAX_PAGES):
        page = params + ([("pageToken", token)] if token else [])
        raw = get(f"{GOOGLE_CALENDAR_LIST_URL}?{urllib.parse.urlencode(page)}", headers=headers)
        if not isinstance(raw, dict):
            break
        for item in raw.get("items") if isinstance(raw.get("items"), list) else []:
            if not isinstance(item, dict) or item.get("primary"):
                continue
            if item.get("selected") is True and isinstance(item.get("id"), str) and item["id"]:
                ids.append(item["id"])
        token = raw.get("nextPageToken")
        if not isinstance(token, str) or not token:
            break
    if len(ids) > MAX_CALENDARS:
        log(f"calendar google: {len(ids)} calendars shown, reading the first {MAX_CALENDARS}")
    return ids[:MAX_CALENDARS]


def _stderr(line):
    print(line, file=sys.stderr)


def _is_401(exc):
    return " 401 " in f" {exc} "


def fetch_google(access_token, time_min, time_max, get=get_json, log=None,
                 clock=time.monotonic, budget_s=GOOGLE_BUDGET_S):
    """Every shown calendar's events in the window, as one events.list body.
    The seam the tests patch.

    The primary is read first and its failure is the account's: that is the
    calendar T9.1 promised. If the calendar list itself fails, the primary is
    still read, alone. Any other calendar that fails is skipped and the rest
    still answer -- a calendar somebody else shared can be unshared between
    the list and the read -- and so is every calendar left when the account's
    time budget runs out. A 401 anywhere is the token, not the calendar, and
    fails the account.

    **The log never names a calendar**: an id is often somebody's e-mail
    address, and an UpstreamError's message carries the URL, which has the id
    in its path. So a 401 from a calendar other than the primary is re-raised
    with a message of this function's own, and the skip lines only count.

    An event on two calendars (an invitation that is also on a shared team
    calendar) is kept once, by its iCalUID and the **instant** it starts --
    not the text, because events.list writes each calendar's times in that
    calendar's own zone. The primary is read first, so its copy is the one
    kept, and a copy the owner declined there hides every other copy too.
    """
    log = log or _stderr
    deadline = clock() + budget_s
    try:
        calendar_ids = fetch_google_calendars(access_token, get=get, log=log)
    except UpstreamError as exc:
        if _is_401(exc):
            raise
        log("calendar google: the calendar list did not answer; reading the primary only")
        calendar_ids = ["primary"]
    items, seen, skipped, late = [], set(), 0, 0
    for calendar_id in calendar_ids:
        if calendar_id != "primary" and clock() > deadline:
            late += 1
            continue
        try:
            raw = fetch_google_events(access_token, calendar_id, time_min, time_max, get=get)
        except UpstreamError as exc:
            if calendar_id == "primary":
                raise
            if _is_401(exc):
                raise UpstreamError("HTTP 401 from a Google calendar") from None
            skipped += 1
            continue
        for item in raw["items"]:
            key = _google_identity(item)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            items.append(item)
    if skipped:
        log(f"calendar google: {skipped} of {len(calendar_ids)} calendars did not answer; skipped")
    if late:
        log(f"calendar google: {late} calendars left unread after {budget_s}s")
    return {"items": items}


def _google_identity(item):
    """(iCalUID, start instant) for an event, or None when it has no iCalUID.

    The instant, parsed, for a timed event; the date for an all-day one. A
    start that does not parse falls back to its text, which can only keep a
    duplicate, never merge two different events.
    """
    if not isinstance(item, dict) or not isinstance(item.get("iCalUID"), str):
        return None
    start = item.get("start") if isinstance(item.get("start"), dict) else {}
    text = start.get("dateTime") or start.get("date")
    return (item["iCalUID"], _parse_instant(start.get("dateTime")) or text)


def fetch_google_events(access_token, calendar_id, time_min, time_max, get=get_json):
    """events.list on one calendar, every page up to MAX_PAGES.

    `timeMin` bounds the event's *end*, so an event already in progress is
    included, which is what the panel wants. `fields` asks for exactly what
    `normalise_google` reads, plus `nextPageToken` and the `iCalUID`
    fetch_google drops duplicates by -- which normalise_google never passes
    on -- so nothing else crosses the wire either.
    """
    params = [
        ("timeMin", _rfc3339(time_min)),
        ("timeMax", _rfc3339(time_max)),
        ("singleEvents", "true"),
        ("orderBy", "startTime"),
        ("maxResults", str(FETCH_PER_ACCOUNT)),
        ("fields", "items(status,summary,eventType,start,end,iCalUID,"
                   "attendees(self,responseStatus)),nextPageToken"),
    ] + [("eventTypes", kind) for kind in GOOGLE_EVENT_TYPES]
    headers = {"Authorization": f"Bearer {access_token}"}
    items, token = [], None
    for _ in range(MAX_PAGES):
        page = params + ([("pageToken", token)] if token else [])
        url = GOOGLE_EVENTS_URL.format(urllib.parse.quote(calendar_id, safe=""))
        raw = get(f"{url}?{urllib.parse.urlencode(page)}", headers=headers)
        if not isinstance(raw, dict):
            break
        items.extend(raw.get("items") if isinstance(raw.get("items"), list) else [])
        token = raw.get("nextPageToken")
        if not isinstance(token, str) or not token:
            break
    return {"items": items}


def fetch_graph(access_token, start, end, get=get_json):
    """calendarView on the default calendar, following `@odata.nextLink` up to
    MAX_PAGES. The seam the tests patch.

    UTC is Graph's documented default ("If not specified, those time values
    are returned in UTC"). `Prefer: outlook.timezone="UTC"` says so anyway,
    because a mailbox setting must not be able to change what this parser
    receives. In UTC every instant is exact, and the all-day case is handled
    in `normalise_graph`. The next page is fetched by its whole URL, as
    Graph asks, never by a `$skiptoken` taken out of it.
    """
    query = urllib.parse.urlencode({
        "startDateTime": _rfc3339(start),
        "endDateTime": _rfc3339(end),
        "$select": "subject,start,end,isAllDay,isCancelled,responseStatus",
        "$orderby": "start/dateTime",
        "$top": str(FETCH_PER_ACCOUNT),
    })
    headers = {"Authorization": f"Bearer {access_token}", "Prefer": 'outlook.timezone="UTC"'}
    url, value = f"{GRAPH_CALENDAR_VIEW_URL}?{query}", []
    for _ in range(MAX_PAGES):
        raw = get(url, headers=headers)
        if not isinstance(raw, dict):
            break
        value.extend(raw.get("value") if isinstance(raw.get("value"), list) else [])
        url = raw.get("@odata.nextLink")
        if not isinstance(url, str) or not url.startswith("https://graph.microsoft.com/"):
            break
    return {"value": value}


def _title(text):
    """A title is text from strangers: anyone can send the owner an invitation.

    Every control and format character goes: C0 and C1 controls, and the
    bidi overrides and zero-width characters that can make a line read as
    something other than what it says (ADR 0017).
    """
    if not isinstance(text, str):
        return None
    text = "".join(" " if unicodedata.category(c) in ("Cc", "Cf") else c for c in text)
    text = " ".join(text.split())
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

    The fraction is seven digits, `2026-09-29T17:00:00.0000000`. It is
    dropped rather than parsed: no calendar is precise to the microsecond,
    and the second is all the panel shows. Raises UpstreamError for an
    instant labelled with any zone but UTC, because guessing it would put
    a meeting at the wrong hour and dropping it would hide it.
    """
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        return None
    zone = str(value.get("timeZone", "UTC")).strip().upper()
    if zone not in UTC_LABELS:
        raise UpstreamError(f"graph returned times in {zone!r}, not UTC")
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
    between UTC-11 and UTC+12 lies within twelve hours of the UTC midnight of
    the same date, so rounding to the nearest one recovers the date. UTC+13
    and +14 are outside that, and so is **New Zealand in summer** (NZDT is
    UTC+13): an all-day event there comes back a day early.
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

    `failed` is `[{source, reason}]`, and `reason` is RECONNECT when the grant
    is over and UNAVAILABLE when the provider or the network is.

    **Never raises, and never serves a stale value.** An account that fails
    costs its own events and is named in `failed`; the others still answer.
    "Never raises" covers any exception at all, not only the two expected
    ones: an account that raised something else used to escape into the
    cache, which kept the previous agenda and retried on every poll.
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
                rows = normalise_google(google(token, now, until, log=log), source)
            else:
                rows = normalise_graph(graph(token, now, until), source)
        except OAuthError as exc:
            reason = RECONNECT if exc.code in AUTH_ERRORS else UNAVAILABLE
            failed.append({"source": source, "reason": reason})
            log(f"calendar {source}: {exc}")
            continue
        except UpstreamError as exc:
            # A 401 from the API itself means the token is no good any more,
            # and a 403 "insufficientPermissions" that it never covered what
            # is asked of it -- a token from before ADR 0019, on a refresh
            # that left `scope` out, would reach the calendar list this way.
            text = f" {exc} "
            reason = (RECONNECT if " 401 " in text
                      or (" 403 " in text and "insufficientPermissions" in text)
                      else UNAVAILABLE)
            failed.append({"source": source, "reason": reason})
            log(f"calendar {source}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - one account must not take the rest
            failed.append({"source": source, "reason": UNAVAILABLE})
            # The type only: an unexpected exception's message is not known
            # to be free of a token or a title.
            log(f"calendar {source}: unexpected {type(exc).__name__}")
            continue
        events.extend(rows)
    return {"accounts": len(accounts),
            "events": select(events, show_titles),
            "failed": failed}
