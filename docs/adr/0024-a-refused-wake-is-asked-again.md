# 0024 — A refused wake is asked for again

Status: accepted · 2026-10-23 (T4.12)
Amends [ADR 0014](0014-poll-loop-outlives-the-screen.md) and
[ADR 0023](0023-a-watchdog-brings-the-service-back.md), which both treated the wake's
`startActivity` as one request that either lands or is a setup mistake.

## Context

On 2026-10-23 the monitor and the phone slept at 12:25 for inactivity. At 13:35:23 the owner
came back, the PC answered, and the app logged `state=online` and `screen=wake`. Android then
logged `Background activity start [... allowBackgroundActivityStart: false; ... inVisibleTask:
false]` and dropped the start. The Activity never resumed, `setTurnScreenOn` never ran, and the
phone stayed `Dozing` while every ping returned `ok`. Nothing asked again. The panel was dark
until somebody pressed the power key.

The exemption that should have covered it, "Display over other apps" (`SYSTEM_ALERT_WINDOW`,
ADR 0023), was `ignore`. It was `allow` on 10-20 (`... allowed because SYSTEM_ALERT_WINDOW` in
the log), the APK had not been reinstalled since 10-19, and nothing in the log says what turned
it off. Two wakes earlier the same day (11:43 and 12:15) had landed without it, because
Android let them through on another exemption, an activity in a visible task. That one depends
on timing, and at 13:35, after 70 minutes dark, it did not apply.

A refused start is dropped by the system, not reported to the app.

## Decision

- **`PanelService` checks every wake request 30 s later** (`WakeRetry.RETRY_MS`), on the main
  looper. The CPU is up for it, because the offline wake lock is held from the request until
  the panel gains focus.
- **`WakeRetry.next(online, interactive)` decides**, in plain Java tested on the JVM: offline
  is `STOP`, a lit display is `SETTLED`, and a dark one is `RETRY`. A lit display is settled
  whoever is in front. Either the panel came up, or a person has the phone in hand, and
  pulling the panel over their app every 30 s is not what a wake is for.
- **`RETRY` logs `wake=retry` and makes the request again**, which books the next check. That
  is at most two retries a minute, and only while the PC is online and the display is dark.
- **`SETTLED` releases the offline wake lock.**
- **Focus settles a wake only on a lit display** (`WakeRetry.showing`). A window keeps or
  regains focus while the display dozes under it, so `panelVisible` then leaves the check
  pending.
- **A request made while the panel is already showing books no check.** That happens when the
  PC goes idle and comes back before the screen times out. No focus changes, so `panelVisible`
  never ran, and the lock used to be held until the PC next went away. A check 30 s out would
  also relight the screen if the owner pressed the power key in between.
- **Each request logs `overlay=denied`** when `Settings.canDrawOverlays` is false. The app
  cannot re-grant it. It can say so next to the `screen=wake` the missing grant undermines.
- Focus comes from `MainActivity.onWindowFocusChanged`, both ways, through
  `PanelService.panelFocus`.

## Consequences

- A wake Android drops is asked for again until it lands or the PC goes away. A retry is
  refused for the same reasons the first request was. It recovers when the reason goes away:
  the task becomes visible, or the grant is restored. No hand on the phone is needed.
- A panel that the owner leaves for another app while the PC is online is not pulled back,
  and neither is a dropped wake on a display somebody turned on. Only a dark display is
  retried.
- While the display stays dark and the PC online, the retries do not end, and the offline wake
  lock is held throughout, as it already was for a wake that had not landed. Each retry is one
  `startActivity` and one log line.
- The covered panel (T4.11) joins the same loop. Since T4.12 its screen-off receiver asks even
  without the grant, so a power press inside another app while the PC is online holds the CPU
  and retries every 30 s until the screen is lit, the PC goes away or the grant comes back. On
  this rig the phone is on mains while a PC is on, so that is accepted.
- Focus that arrives while the display is still dark leaves the check pending, and no later
  focus settles it. A power press to put the screen out in the 30 s that follow is then met by
  a retry that lights it again. Online, the screen is supposed to be on (invariant 3), so this
  is left as is.
- `overlay=denied` makes a lost grant visible in the log before a dark morning. It does not
  fix it. Re-granting is still INSTALL-PHONE step 4.
