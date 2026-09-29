# 0014 — The poll loop outlives the screen: a foreground service owns it

Status: accepted · 2026-09-19 · power-aware branch written and measured 2026-09-19 (T5.6)
Amends [ADR 0005](0005-real-screen-sleep.md), which describes the screen policy and says
nothing about who stays awake to enforce it.

## Context

[ADR 0005](0005-real-screen-sleep.md) and invariant 3 say the panel clears
`FLAG_KEEP_SCREEN_ON` when the PC goes away and lets Android sleep the display. T4.2 put the
poll loop in the Activity: `PcPoller.start()` in `onResume`, `stop()` in `onPause`. Each half
was right on its own, and together they are a contradiction.

The screen going out delivers `onPause` and then `onStop` to the foreground Activity. So the
moment the panel does what it exists to do, it switches off the only thing that would notice
the PC coming back. `screen=wake` can never fire. Nothing was broken while
`setKeepScreenOn(true)` was still unconditional in `onCreate` — the screen never went out, so
`onPause` never came — which is why the fault survived T4.2's five green criteria.

Moving to `onStart`/`onStop` does not help: the screen going out reaches `onStop` too.

Three properties have to hold at once, and no single mechanism gives all three:

1. **Something must still be running** while the Activity is stopped, for hours.
2. **The CPU must be awake** often enough to probe. A stopped process is not exempt from
   suspend, and a `ScheduledExecutorService` in a suspended device simply does not fire.
3. **Something must resume the Activity** when the PC returns. `setTurnScreenOn(true)` is a
   property of the Activity's window and takes effect when that window next becomes visible;
   it does not wake anything by being set.

There is a fourth, older constraint: **MIUI's battery manager freezes background apps.** That
is the project's most expensive trap, already documented in `docs/INSTALL-PHONE.md` as two
manual per-device toggles. A background thread inside a stopped Activity is exactly what it
freezes.

## Decision

**A started foreground service, `PanelService`, owns `PcPoller`.** It is created by
`MainActivity.onCreate` and stopped only when the Activity is actually finishing — a stop
caused by the screen going out does not reach `onDestroy`, which is precisely the distinction
this needed.

- **Still running (1):** a foreground service is the platform's own answer, and the category
  MIUI's exemptions are written against. It does not replace the manual toggles; it is what
  makes them mean something. The price is a permanent notification, which the panel hides
  anyway (the status bar is gone, T2.3) and which nobody sees while the screen is off.
- **CPU awake (2):** a `PARTIAL_WAKE_LOCK`, acquired on the transition to offline *while the
  phone is on mains* and dropped once the panel's window actually has focus again. Offline on
  battery it is deliberately not held at all, and `AlarmManager` keeps the time instead — see
  the measurement below. Online it would be redundant, because
  `FLAG_KEEP_SCREEN_ON` already keeps the device up — but *asking* for the wake is not the same
  as getting it. `startActivity` only hands the request to the ActivityManager and returns, so
  releasing there would drop the app's only claim on the CPU with the wake still in flight, and
  in the MIUI denial described below the window never comes up at all. Focus is the first moment
  anything can be sure the display is on, so that is where the lock goes.
- **Resuming (3):** on the transition to online the service starts `MainActivity` with
  `FLAG_ACTIVITY_REORDER_TO_FRONT`, so the existing task is raised rather than a second one
  created. That is a background activity start, permitted because the app has an activity in
  the back stack of a task on the Recents screen. In practice MIUI still relaunches the
  Activity on the way back from a doze — see the consequences below; the flag keeps the task
  identity, not the instance.

Ownership after this change: `PcState` decides what a probe means, `PcPoller` owns the socket
and the schedule, `PanelService` stays awake and logs `state=`, `MainActivity` owns the window
and logs `screen=`. No component holds two of those.

### The service replays state to a window that arrives late

`PcPoller` delivers edges and nothing else, which is what keeps one marker per transition
honest. It also means a window that appears *between* two transitions is told nothing at all,
and both ways that happens are real on this device: MIUI relaunches the Activity on the way back
from a doze, and `START_STICKY` can restart the service into a process with no Activity in it.

Left alone, the newcomer keeps whatever state `onCreate` guessed. `onCreate` guesses online —
correctly, for a launch somebody is watching — so a relaunch during an offline night would hold
`FLAG_KEEP_SCREEN_ON` and show the online layout until the PC next came back. That is the exact
breach of invariant 3 this wave exists to prevent, arrived at from the other direction.

So `PanelService` remembers the last state and replays it on registration. A replay does not log
a marker, because an Activity relaunch is not a transition — with one exception that matters:
when the transition itself happened while no window was registered, the marker was never logged
at all, and the window that finally registers owns it. Without that exception the `START_STICKY`
restart this ADR asks for would come back watching and never say so.

### Why a wake lock is affordable, and the assumption under it

Holding a partial wake lock through every hour the PC is off would normally be indefensible
here: [ADR 0008](0008-device-longevity.md) makes adaptive polling and real screen sleep
requirements rather than polish, on the grounds that the phone runs on its own battery whenever
the PC is off.

**On this rig it does not.** The board keeps USB powered with the PC shut down, so the phone is
charging in exactly the state this wake lock is held. "Offline" means charging with the screen
off, and the lock costs a little heat rather than an overnight discharge. Against that, the
screen — by far the larger draw — has just been switched off, which is the trade this whole
wave exists to make.

That is an assumption about one desk, and it is written here so it can be checked rather than
inherited. **If ErP Ready is ever disabled in the BIOS, as `docs/DEVICE-CARE.md` recommends,
this decision is wrong from that day on** and the service has to become power-aware: drop the
wake lock while discharging, fall back to `AlarmManager` for a sparse offline probe, and take
`ACTION_POWER_CONNECTED` as the immediate signal that the PC has just come back — which, with
ErP off, is exactly what USB power returning means.

### The assumption was measured, and it was false — for a different reason (T5.6, 2026-09-19)

The branch above is **written**. What the measurement found is worth recording, because the
prediction in it was wrong in an instructive way.

ErP Ready was never the problem. USB stays live with the PC on *and* off, exactly as assumed.
What the desk actually reports is:

```
Max charging current: 100000      # 100 mA
level 22 at 12:44  ->  level 20 at 13:11
```

The port negotiates **100 mA**, and the panel with its screen on draws several times that. So
the phone discharges at about 4.4% an hour *while the framework reports `status: 2`, charging*.
"Offline means charging with the screen off" was true about the cable and false about the
arithmetic — the supply is simply smaller than the draw, and this ADR's reasoning never
considered that a live cable might not be enough.

**And the branch's trigger is narrower than the problem.** Dormancy means `EXTRA_PLUGGED == 0`,
and a phone that drains *while plugged* is not that. Whether this desk ever reaches the dormant
state depends on something still unmeasured: if the board keeps USB live with the PC off, the
phone reads as plugged all night and the wake lock is held exactly as before. Keying dormancy on
net discharge instead was considered and rejected — `Charge counter` is frozen on this device,
`current_now` is unreadable, and `BATTERY_PROPERTY_CURRENT_NOW`'s sign convention varies by OEM,
so it would be a threshold heuristic on a badly reported number deciding whether the panel may
sleep. The branch is correct for the state it names; making that state occur on this desk is a
power-source question.

Two consequences, and they pull in different directions:

- **The branch is more valuable than this ADR thought.** With the screen off, a partial wake
  lock costs something like 60–120 mA against 100 mA coming in: roughly break-even, so the phone
  hovers rather than recovers. Dropping the lock turns those hours net-positive, which is the
  difference between a panel that charges overnight and one that starts each morning lower than
  the last.
- **The branch does not fix the online case, and no code can.** While anybody is looking at the
  panel it draws more than the port supplies. That is a power source, not a decision — see
  T5.6's notes.

The claim that the branch "cannot be tested on this desk today" was also wrong, and it was the
weakest part of this ADR. `adb shell dumpsys battery unplug` overrides what the framework
reports and fires the real `ACTION_POWER_DISCONNECTED`, which is the layer the app reads; `reset`
fires `ACTION_POWER_CONNECTED`. The whole branch is exercised in about two minutes without
touching the cable or the BIOS. **Untestability is worth checking before it is used as a reason
not to write something.**

## Alternatives rejected

- **`AlarmManager` alone**, with no service and no wake lock. Cheapest, and it fails the
  responsiveness requirement: on battery and in Doze the platform clamps exact alarms to
  roughly nine minutes, so the panel would come back minutes after the login instead of within
  the 15s `PcState.BACKOFF_CAP_MS` promises.
- **A partial wake lock held by the Activity**, with the loop moved to `onCreate`/`onDestroy`
  and no service at all. Fewer components, and it is the version MIUI freezes.
- **Keeping `FLAG_KEEP_SCREEN_ON` held permanently** and going back to `screenBrightness = 0f`
  plus a black render. This is the ADR 0005 fallback, and it dissolves the problem by never
  letting the Activity stop — at the cost of the largest longevity win in the project. Kept as
  the fallback it already was, not promoted for the convenience of the poll loop.

## Consequences

- A second component in a project whose Android layer was "one Activity, one WebView". The rule
  in `android/CLAUDE.md` is about the UI and stands; this is not a second screen.
- A permanent notification, invisible in normal use.
- Three new permissions: `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE`, `WAKE_LOCK`
  (plus `POST_NOTIFICATIONS`, which matters only above API 33). `specialUse` is the honest
  foreground service type: this is not media, a download or a location fix, and the platform
  has no category for a desk panel watching for a login.
- **The panel does not go dark the instant the PC does.** It goes dark one device display
  timeout later, because invariant 3 forbids the app from owning that timer. Shortening it is a
  device setting, not an app change.
- The markers still fire at the moment of the decision, not at the moment the display obeys, so
  the 20s allowances in `docs/TESTING.md`'s scenarios are unaffected — `screen=sleep` lands within the poll interval
  and the panel goes dark up to a display timeout later. What that separation costs is the
  meaning of the marker: `screen=sleep` says the app asked, never that the panel went out.
  Proving it went out is eyes-only and stays in T4.4's manual check.
- **The wake relaunches the Activity**, so the page reloads and a `panel=rendered` follows each
  `screen=wake` by about a second. Measured, not assumed. T2.3 declined to add
  `android:configChanges` on the grounds that nothing relaunched the Activity; that is no
  longer true on this path, and anything counting `panel=rendered` across a wake has to allow
  for it. It is left alone deliberately: a reload on wake costs about a second of an already
  dark screen and hands the panel a fresh page, which is the state it wants anyway.
- **Raising the Activity needs a permission MIUI denies by default** — "Show on Lock screen".
  Without it every marker is still correct and the screen still does not come on. The failure is
  invisible except for one `MIUILOG-` line, which is why it is now a numbered step in
  `docs/INSTALL-PHONE.md` rather than a footnote.
- `START_STICKY`: if MIUI kills the process anyway, the panel comes back watching rather than
  staying dark with the PC on.
- **The sparse alarm only works if the app is exempt from Android's battery optimisation**
  (T5.6). Without it this device deferred a 15-minute allow-while-idle alarm to **three days**,
  while still listing it as armed — so the panel would have gone dormant exactly as designed and
  then never woken. MIUI's own "No restrictions" is a different list and does not cover it;
  `docs/INSTALL-PHONE.md` step 6 is the one that does. This makes a per-device toggle
  load-bearing for a code path, which is uncomfortable and is the honest position: the
  alternative is a wake lock held all night, which is what this branch exists to stop.
- **Offline on battery, recovery without a power event takes up to about half an hour** (T5.6).
  `PcState.DORMANT_ALARM_MS` asks for fifteen minutes, and that is the request rather than the
  bound: `setAndAllowWhileIdle` is inexact and the platform adds a window of its own — measured
  here as `whenElapsed=+14m41s maxWhenElapsed=+25m56s`, eleven minutes on top. A check that
  waited eighteen minutes found the alarm still legitimately pending. Read `maxWhenElapsed`, not
  the constant. It is only ever paid in the
  configuration where the phone is on its own charger while the PC is off: with the USB dying
  with the PC, `ACTION_POWER_CONNECTED` arrives the moment the PC returns and the alarm never
  matters.
- **An eighth logcat marker, `dormant=on|off`** (T5.6). `Markers.java` says to resist adding
  more, and the justification is that everything else about dormancy is an *absence* — no
  `ping=`, no wake lock, no `data=` — and an absence cannot be told from a poll loop that has
  silently died, which is the failure T5.2 calls the worst available. This is the one line that
  says the silence was deliberate.

## References

- <https://developer.android.com/develop/background-work/services/fgs>
- <https://developer.android.com/develop/background-work/background-tasks/awake/wakelock>
- <https://developer.android.com/guide/components/activities/background-starts>
- <https://developer.android.com/reference/android/app/Activity#setTurnScreenOn(boolean)>
