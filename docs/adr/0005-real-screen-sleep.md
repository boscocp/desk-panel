# 0005 — Let the screen really sleep; dim-to-black is the fallback

Status: accepted · 2026-09-13
Supersedes an earlier draft of this project that specified dim-to-black as the primary approach.

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
