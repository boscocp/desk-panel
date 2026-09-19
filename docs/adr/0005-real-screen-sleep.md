# 0005 — Let the screen really sleep; dim-to-black is the fallback

Status: accepted, primary mechanism **validated on the device** · 2026-09-13, validated
2026-09-19
Supersedes an earlier draft of this project that specified dim-to-black as the primary approach.
Amended by [ADR 0014](0014-poll-loop-outlives-the-screen.md), which decides who stays awake to
enforce this policy once the Activity is allowed to stop.

## Outcome (T4.4, 2026-09-19)

**MIUI honours it. The primary design stands and the fallback is not needed.** On the Redmi
Note 10, MIUI 14 / Android 12, four consecutive offline-online cycles took the display from
`mWakefulness=Dozing` to `Awake` with nobody touching the phone, and `screen=sleep` /
`screen=wake` were logged once each per transition. `screenBrightness` was left at `-1f`
throughout; nothing in the app dims anything any more. `docs/DEVICE-CARE.md` may keep asserting
the behaviour as fact.

Two conditions, both outside the code, and the panel fails silently without either:

- **MIUI's "Show on Lock screen" permission must be granted.** Denied — which is the default —
  the Activity is raised, `state=online` and `screen=wake` are both logged, and the screen
  stays dark, because the window is never allowed over the keyguard. MIUI says so in logcat and
  nowhere else: `MIUILOG- Show when locked PermissionDenied pkg : dev.bosco.deskpanel`. It is
  an app-op, and `adb install -r` resets it.
- **Developer options → "Stay awake" must be off.** On, the screen never sleeps at all while
  charging, and the phone on this desk is always charging.

Both are now steps in `docs/INSTALL-PHONE.md`. The device PIN turned out not to matter: the
keyguard was up (`isKeyguardLocked=true`) in every successful cycle, and the permission — not
the lock — is what decides it.

The fallback below is kept as documentation of a road not taken. Nothing in the code implements
it any more, so reinstating it means writing it, not flipping a flag.

## Context

When the PC is off, the panel should be off. The first design assumed no public API could wake
a sleeping Android screen, and worked around it by never sleeping: hold `FLAG_KEEP_SCREEN_ON`
permanently, and on "PC offline" set `screenBrightness = 0f` and render pure black. On AMOLED,
black pixels are off pixels, so it looks convincing.

That assumption was wrong. `Activity.setTurnScreenOn(boolean)` was added in API 27 and is **not
deprecated** — the deprecated things are the old `FLAG_TURN_SCREEN_ON` and the screen wake
locks (`ACQUIRE_CAUSES_WAKEUP`, deprecated in API 17). The target device is API 31.

The difference matters more once ErP Ready is disabled in the BIOS (see ADR 0008): the phone
then runs on its own battery whenever the PC is off. A lit display showing black still draws
power and still ages the panel.

## Decision

- **Online:** hold `FLAG_KEEP_SCREEN_ON`.
- **Offline:** clear the flag and let Android sleep the screen normally.
- **Back online:** `setTurnScreenOn(true)` together with `setShowWhenLocked(true)`.

`screenBrightness = 0f` plus a black render is kept as a **documented fallback**, to be used
only if MIUI proves unreliable at waking the screen. Task T4.4 makes that determination on the
real device, and the outcome is recorded here.

## Consequences

- Real power saving during the many hours the PC is off — the single largest longevity win in
  the project.
- Burn-in stops being a concern in the offline state, because nothing is being displayed.
- Genuinely dark: no residual glow in a dark room, which `screenBrightness = 0f` cannot promise
  (it is the minimum controllable brightness, not "off", and MIUI has a reputation for clamping
  it higher than requested).
- **Risk:** waking reliably from a vendor ROM is not guaranteed, and `setShowWhenLocked` has to
  get past the lock screen. Hence the fallback, and hence T4.4 validating on hardware rather
  than on documentation.
- The app must emit `screen=sleep` / `screen=wake` markers so the E2E suite can assert on the
  transition (ADR 0009).

## References

- <https://developer.android.com/develop/background-work/background-tasks/awake/screen-on>
- <https://developer.android.com/reference/android/app/Activity#setTurnScreenOn(boolean)>
