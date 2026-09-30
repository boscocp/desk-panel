# 0019 — Google reads every calendar the owner shows, still read-only

Status: accepted · 2026-09-30
Amends [ADR 0017](0017-calendars-are-personal-data.md), for Google only: its scope and its
"primary calendar only". Everything else in 0017 stands.

## Context

ADR 0017 chose `calendar.events.owned.readonly`, "See the events on Google calendars you own",
and read only `calendars/primary`. On the owner's first full day with the panel the AGENDA card
said "nada à vista" while Google Calendar showed events: they were on calendars **shared with
the owner or subscribed to**, which the owner does not own. The grant could not reach them, so
the server never asked.

The owner asked for those calendars on the panel, knowing the scope had to widen.

## Decision

### Two read-only scopes, both required

| Scope | Google's description | Why |
|---|---|---|
| `https://www.googleapis.com/auth/calendar.events.readonly` | "View events on all your calendars" | The events, on every calendar in the account. |
| `https://www.googleapis.com/auth/calendar.calendarlist.readonly` | "See the list of Google calendars you're subscribed to" | Which calendars exist, and which the owner has switched on. |

Descriptions from
[developers.google.com/workspace/calendar/api/auth](https://developers.google.com/workspace/calendar/api/auth),
read 2026-09-30.

These are the narrowest pair that reaches the owner's other calendars. `calendar.readonly` was
the alternative: one scope, but "See and download any calendar you can access", which also
covers calendar settings and the download of whole calendars. The panel needs neither.

The rules ADR 0017 wrote into the code are unchanged, and apply to the new pair:

- `oauth.check_scope` compares every grant with the allowlist, at login and at every refresh.
  Both scopes are now **required**, so unticking either on the consent screen fails the login.
- `calendar.events.owned.readonly` stays on the allowlist and is no longer required. Google may
  hand back a scope an account granted the same client before, beside the new ones. A grant of
  that scope alone, a token from before this record, fails the check, and the card says
  "reconectar" until the owner logs in again.
- The guard test still fails the build over any scope outside the allowlist and over any
  calendar request that is not a `GET`. It now also asserts that the write twin of each new
  scope (`calendar.events`, `calendar.calendarlist`) and `calendar` are off it.

### Which calendars

The ones the owner has switched on in Google Calendar: `selected` in the calendar list, which
is the checkbox beside each calendar in Google Calendar's own sidebar. Hidden calendars are not
listed at all. The primary is always read. At most `MAX_CALENDARS` (10) in all.

The panel therefore shows what the owner already chose to look at, and a calendar the owner
unticks leaves the panel at the next refresh without a config change.

### Failure

The primary failing fails the account, as before. Any other calendar that fails is skipped and
the rest still answer: a calendar somebody else shared can be unshared between the list and the
read. A 401 on any calendar is the token, not the calendar, and fails the account. The log
never names a calendar, because a calendar's id is often somebody's e-mail address.

An event on two calendars (an invitation that is also on a shared team calendar) is kept once,
by its `iCalUID` and start. The `iCalUID` is read for that and never leaves the server.

## Consequences

- **More personal data reaches the LAN, and some of it is other people's.** A shared calendar
  is often a family member's or a colleague's, and its titles are theirs. ADR 0017's exposure
  stands and grows with it: anyone on the Wi-Fi can read `/quotes` until T9.4 lands.
  `calendar_show_titles = false` is the owner's lever, as before.
- **A subscribed work calendar is work data.** If the owner has added a copy of an employer's
  calendar to Google, this change puts it on the panel. Whether that is allowed is the
  employer's policy, as ADR 0017 already says of connecting a work account directly.
- **Every existing Google login has to run again**, on every machine that serves the panel,
  after the two scopes are added to the OAuth client's consent screen.
- **More requests.** One calendar list and one events request per shown calendar, every
  `calendar_interval_s`, off the request path. Well inside Google's 600 requests a minute per
  user.
- Microsoft is unchanged: `Calendars.ReadBasic`, the default calendar.
