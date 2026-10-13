# 0023 — A watchdog alarm brings the service back

Status: accepted · 2026-10-13 (T4.10)
Amends [ADR 0014](0014-poll-loop-outlives-the-screen.md), which relied on `START_STICKY` for
the case where the process is killed anyway.

## Context

On 2026-10-13 at 03:18:58 the Play Store updated Android System WebView. Android killed this
app as a WebView dependent: `am_kill … stop com.google.android.webview due to installPackageLI`,
`exit-info` reason 10 (USER REQUESTED). The service did not come back. That kind of kill does
not allow a restart, so `START_STICKY` did nothing. The panel stayed dead until it was launched
by hand six hours later, and the PC that came up in the morning lit nothing.

`adb shell am force-stop com.google.android.webview` reproduces the kill: the same reason and
the same `stop com.google.android.webview due to …` text. After it, nothing restarted the app
for 90 s. The app itself was not marked stopped (`stopped=false`), so its own alarms survive the
kill.

## Decision

- **`PanelService` keeps a watchdog alarm armed.** It is a one-shot `setAndAllowWhileIdle`
  `ELAPSED_REALTIME_WAKEUP` alarm 15 minutes out, re-armed on every `onStartCommand`, its own
  firings included. A repeating alarm is deferred in Doze. An allow-while-idle one is not, as
  long as the app is on the allowlist below. Without it, `INSTALL-PHONE.md` step 6 measured this
  kind of alarm deferred by three days.
- **It targets the service, not a receiver.** `PendingIntent.getForegroundService` with
  `ACTION_WATCHDOG` lands whether or not a process exists. If the service is alive, the
  firing is one redundant start command. If not, it starts the service. The service polls, finds
  the PC, and brings the panel to the front the same way a wake from sleep does.
- **The background start is allowed because the app is on the battery-optimisation
  allowlist.** `INSTALL-PHONE.md` step 6 sets that and checks it after every install. Without
  the allowlist, Android 12 refuses a foreground service started from the background.
- **`onDestroy` cancels it.** A deliberate stop, when the panel finishes, reaches
  `onDestroy`. A kill does not. That difference is what the watchdog relies on.
- A revival logs `service revived by watchdog`, plain text and not a marker, because no state
  changed.

## Consequences

- After a kill that leaves the app not stopped (`stopped=false`), the panel is back within
  15 minutes plus the platform's inexact window. AOSP allows up to 0.75 × the delay, so the
  worst case is about 26 minutes. That was measured for the WebView kill. A MIUI memory kill
  is covered only if it also leaves `stopped=false`, which nobody has measured.
- A swipe from recents that finishes the Activity is a deliberate stop. `stopIfUnclaimed`
  reaches `onDestroy`, the watchdog is cancelled, and the panel stays away, as before.
- `am force-stop dev.bosco.deskpanel`, or *Force stop* in Settings, clears the app's alarms
  and the app stays dead, as Android intends. A reboot clears alarms too. The app has no boot
  receiver. Whatever brings the panel back after a reboot (`INSTALL-PHONE.md` expects it to,
  and it was not re-measured here) also re-arms the watchdog, because it goes through
  `onStartCommand`.
- On battery with the PC away, the phone wakes once per 15 minutes for the watchdog, on top of
  the dormant probe's 15 minutes. Each wakeup is one start command and no network.
