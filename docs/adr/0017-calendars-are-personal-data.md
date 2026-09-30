# 0017 — Calendars are personal data, and the grant is read-only

Status: accepted · 2026-09-29 (T9.1) · Google's scope and "primary calendar only" amended by
[ADR 0019](0019-every-google-calendar-the-owner-shows.md)
Amends [ADR 0004](0004-server-is-login-signal-and-proxy.md), whose proxy so far carried only
public data, and extends the threat model of [ADR 0015](0015-the-panel-can-act-on-the-pc.md).

## Context

Every upstream this server has proxied so far is public: a stock price, an exchange rate, the
weather, the moon. Anyone on the Wi-Fi can read `/quotes`, and until now that meant they could
read what any website would have told them.

T9.1 puts the owner's next meeting on the panel, from Google Calendar and from Microsoft Outlook.
That changes three things at once:

- **The payload carries personal data**, and some of it is about people who are not the owner:
  an event title often names someone.
- **The server holds credentials that outlive a session.** A refresh token lets the holder read
  a calendar for months, and it sits in a file on a desktop PC.
- **The server has no authentication**, deliberately (ADR 0004, ADR 0015). That decision is not
  reopened here. A token on the phone would live in the APK, and anyone who can reach the port
  can download the APK from `/app`.

So this record states what the server may ask for, what it may keep, what the panel may show,
and what a stranger on the LAN, or a web page the owner visits, can get.

## Decision

### The grant is read-only, and it is the smallest one that works

| Provider | Scope requested | Why this one |
|---|---|---|
| Google | `https://www.googleapis.com/auth/calendar.events.owned.readonly` (superseded by [ADR 0019](0019-every-google-calendar-the-owner-shows.md)) | Reads events on calendars the owner owns. Cannot write, cannot list other people's calendars, cannot see free/busy of anyone else. |
| Microsoft | `Calendars.ReadBasic offline_access` | Reads events without body, attachments or extensions. No admin consent required. `offline_access` is what returns a refresh token. |

Only the **primary** calendar is read (`calendars/primary`, `/me/calendar/calendarView`).
**Superseded for Google by [ADR 0019](0019-every-google-calendar-the-owner-shows.md)**, which
reads every calendar the owner shows, with `calendar.events.readonly` and
`calendar.calendarlist.readonly`.

Two checks enforce this in the code, not only in this record:

- **The granted scope is compared to the requested one** after every token response, at login
  and at every refresh. A grant that carries anything outside a short read-only list is refused.
  - At login, nothing is stored, and a broad Google grant is revoked on the spot.
  - At a refresh, the stored token is deleted.
  - The owner cannot tick an extra box on a consent screen and end up with a write token on the
    desk.
  - A response with no `scope` field means the scope requested (RFC 6749 section 5.1, and
    Microsoft documents the same). That request is read-only by construction.
- **A guard test fails the build** unless every Google scope URL and every Graph permission
  named anywhere in `server/*.py` is on the read-only allowlist. It also fails if a calendar
  request uses any method but `GET`.

### Credentials stay on the PC, in their own file

- **The flows run on the PC, never on the phone.**
  - Google uses the installed-app flow: a loopback redirect to `127.0.0.1` with PKCE S256.
    Google's device authorization grant was the first plan and cannot work, because Google's
    list of scopes allowed on that flow contains no Calendar scope at all
    (developers.google.com/identity/protocols/oauth2/limited-input-device).
  - Microsoft uses the device code flow, as a public client with no secret.
- **The loopback listener is as small as a listener can be.** It binds `127.0.0.1` on a random
  port, it runs only while the owner is running `server/calendar_login.py`, it checks `state`,
  it accepts one redirect and it closes after a timeout. It is not the panel's server and it is
  not on the LAN.
- **Tokens live in `server/calendar-tokens.json`, not in `config.toml`.** Microsoft replaces
  the refresh token on every use, so the server has to *write* its credentials. A server that
  rewrote the hand-edited `config.toml` would destroy its comments, and the comments are the
  documentation (T3.12). The tokens file is gitignored, created with mode `0600`, written
  atomically (temporary file, then `os.replace`), and covered by the same permission warning
  as the brapi token.
- **Nothing credential-shaped reaches `android/` or `web/`.** T9.1's acceptance greps for it,
  and `scripts/check_secrets.py` knows the shape of a Google refresh token and a Google client
  secret.
- The Google "Desktop app" client secret is, by Google's own documentation, "obviously not
  treated as a secret" (developers.google.com/identity/protocols/oauth2). It lives in the
  gitignored `config.toml` anyway, because a value that is harmless alone is still one half of
  a pair.

### What the panel receives

The server sends at most five upcoming events, three with a time and two all-day, each with
`start`, `end`, `allDay`, `source`
(`google/personal`), and `title`. Nothing else leaves the server: no attendees, location, body,
link, organiser or event id.

Declined and cancelled events are filtered **on the server**, so an event the owner said no to
is never on the LAN at all.

**A title is text from strangers.** Anyone can send the owner an invitation, and it lands on the
calendar with whatever title the sender chose. So a title is treated as hostile input all the
way down:

- On the server, every control and format character is stripped: C0 and C1, bidi overrides,
  and zero-width characters. The title is then cut to 80 characters.
- `DataPayload` escapes the whole payload for the script it is injected into, as it always has.
- Both themes write the title with `textContent`, never as markup.

An invitation can put words on the panel, and it cannot put anything else there.

**Titles are shown by default** (`calendar_show_titles = true`). That is the owner's decision,
asked for explicitly on 2026-09-29, and it has this cost, which the example config states
beside the key: **anyone on the same Wi-Fi can read the titles of the owner's next five
events.** Set it to `false` and the title is removed on the server, before the payload is
built, so the panel says `in 25 min` and the LAN learns only that there is a meeting.

### What a web page can get, and why it now gets nothing

A web page the owner visits cannot read `/quotes` today: it is cross-origin, and the server
sends no CORS headers. **DNS rebinding** is the way around that. A page on `evil.example`
re-points its own name at the PC's LAN address, and from then on its requests to
`evil.example:8777` are same-origin and readable. With titles on, that would put the owner's
calendar in a stranger's hands without them being anywhere near the Wi-Fi.

So **every route checks the `Host` header**. It must be an IP literal, `localhost`, or a name
listed in `allowed_hosts`, and anything else is answered `421 Misdirected Request` before any
route runs. A rebinding attack always arrives carrying its own hostname, because that is the
name the browser resolved. The phone, `curl` and `probe.py` all address the PC by IP, and every
URL in the documentation does too.

### Failure is loud, per account, and never stale

A price from five minutes ago is still useful, and a meeting from five minutes ago may be one
already missed. So the calendar is the one upstream whose failure is **not** served stale.

- An account that fails costs its own events, and only its own. That holds for any exception,
  not just the expected ones.
- The payload names the account in `failed`, with a reason:
  - `reconnect`: the grant is over, and `calendar_login.py` fixes it.
  - `unavailable`: the provider or the network is down, and the next cycle retries by itself.
- The card says which. The server log names the provider and the account, never the token,
  the authorisation code or a title.
- **A refused token is not sent again.** After an auth error, that token is remembered as dead,
  and no request goes out until the store holds a different one. A provider that is merely
  down is retried at the next cycle.

### What the owner has to know before connecting a work account

Microsoft's work and school accounts belong to a tenant, and the tenant decides.

- An administrator may have disabled user consent, or allowed it only for verified publishers.
  A personal app registration is neither, so the login ends in an admin-consent request and the
  account is simply not connected.
- Putting an employer's calendar on a panel at home is a question for the employer's data
  policy, and this project cannot answer it. The setup guide says so where the work account is
  connected.

## Consequences

- **The Google refresh token expires after seven days** while the OAuth consent screen is in
  "Testing" with an external user type. The setup guide therefore says to publish it as "In
  production". It stays unverified, which Google allows for personal use under 100 users, and
  the owner clicks past the unverified-app warning once.
- **A Google token can still die silently.** Six months unused, a revocation, or a hundredth
  newer token for the same client all invalidate it. The panel says `reconnect` and the log
  names the account.
- **The fixtures are written from the documentation, not recorded.** No live response from
  either provider has been captured, because that needs the owner's account. The shapes are a
  premise until `contract_calendar.py` runs green once. Two defences keep a wrong premise loud
  rather than silent:
  - a Graph instant labelled with any zone but UTC fails the account;
  - the contract test fails if the normaliser drops an event the filters would have kept.
- **On Windows the token file is as private as the folder the repository is cloned into.**
  Mode bits do nothing there.
  - Inside the user's profile (`C:\Users\<name>\...`), only that user can read the file.
  - At `C:\desk-panel` it inherits the drive root's ACL.
  - In a folder OneDrive syncs, the file goes to the cloud.
  - The setup guide says where to clone.
- **The Microsoft client id can be borrowed.** A public, multi-tenant registration with public
  client flows on is what lets one registration serve a personal and a work account. Anyone can
  start a device code flow with its id and send the code to someone else, who would see the
  owner's app name on the consent screen. The victim's calendar is what is at risk, not the
  owner's, and the scope is still `Calendars.ReadBasic`.
  - An owner with only a personal account can register for personal accounts only, which
    narrows this.
  - The id is in no committed file.
- **Revoking is partly automated.**
  - `calendar_login.py --disconnect` revokes a Google grant (`POST
    https://oauth2.googleapis.com/revoke`) and says whether Google agreed. Access can also be
    removed at myaccount.google.com/permissions.
  - Microsoft has no per-app revocation endpoint. The owner removes the app at
    myapplications.microsoft.com (work or school) or at account.live.com/consent/Manage
    (personal; the page behind that URL was not checked without a session).
  - Deleting `server/calendar-tokens.json` disconnects every account on that PC.
- **One APK rebuild.** `DataPayload.merge` rebuilds the payload key by key, so `agenda` needs a
  line there once. After that, which accounts, whether titles are shown and how far ahead to
  look are all `config.toml`.
- **With more than one PC** (ADR 0016), each PC has its own tokens file and shows its own
  owner's calendars, which is the same rule its tickers already follow.
