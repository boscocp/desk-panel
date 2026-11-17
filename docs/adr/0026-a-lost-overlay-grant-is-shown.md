# 0026 — A lost overlay grant is logged when it goes, and shown on the panel

Status: accepted · 2026-11-17 (T4.15)
Amends [ADR 0024](0024-a-refused-wake-is-asked-again.md), which made a missing grant visible
only at the moment it costs a wake.

## Context

"Display over other apps" (`SYSTEM_ALERT_WINDOW`) is what lets a service revived by the
watchdog raise the panel (ADR 0023). On this phone it goes from `allow` to `ignore` with no
install near it: 2026-10-23, 10-28, 10-30, 11-04, and again between 11-06 and 11-16. Nobody
knows what switches it off. Waves 50, 51 and 52 each recommended finding out, and none could:
the app-op's history keeps the last access and the last rejection, not the last change.

The 11-16 outage shows why that matters. The grant had been in use on 11-06 12:35, and the
panel worked for ten more days without it, because the Activity stayed alive and a live task
needs no exemption. At 15:49 a WebView update killed the app. At 16:19 the watchdog revived
the service, and from then on every `state=online` went unanswered: two logins at the PC and
one at the Mac, until the owner pressed the power key at 10:01 the next day. `overlay=denied`
was in the log every 30 s from 09:23, but nobody reads logcat on a dark morning, and the line
only appears after the grant has already cost a wake.

## Decision

1. **The service watches the grant.** `AppOpsManager.startWatchingMode` on
   `OPSTR_SYSTEM_ALERT_WINDOW`, plus a re-read on every battery broadcast as a backstop. The
   first reading that finds it missing logs `overlay=lost`, including a service's first
   reading, and its return logs `overlay=back`. The decision is `OverlayGrant.change`, plain
   Java. The next loss then has a timestamp, which is what finding its cause needs.
2. **The panel says so while it is still lit.** The service folds `"overlay": false` into the
   battery object of the payload. `batteryFields` reads it, and both themes draw the phone's
   battery line with a red note, `sem sobrepor apps` or `no overlay grant`. The words match
   the setting's name on the phone. While the grant is held nothing is added, so every payload
   and fixture before T4.15 is unchanged.

## Consequences

- A lost grant is visible on the day it goes, while the panel is lit, rather than on the
  morning after the next kill.
- The cause of the loss is still unknown. `overlay=lost` gives it a time to look up next to
  the rest of the log, and the main log is a 256 KiB ring, so it has to be read within the
  hour. `adb logcat -b main -G 4M` buys more.
- The note rides the battery line, which is the phone's own state. It is not a payload key of
  its own, because the only thing that reads it is the line that already describes the phone.
- No new bridge and no new timer: the watcher is a system callback, and the backstop rides a
  broadcast the service already receives.
