# End-to-end suite

Drives the real phone over adb. The suite itself is built in task TT.8; this file describes
it ahead of time, which is why nothing here runs yet.

## Prerequisites

- Phone reachable over adb (see `docs/INSTALL-PHONE.md`)
- The app installed, with MIUI autostart and battery exemption already granted
- `server/config.toml` (or the older `server/config.json`) present and valid

## Running

```bash
python e2e/run_e2e.py
echo $?    # 0 means every scenario passed
```

Slow by design — over a minute — so it is not part of `make check`.

## Scenarios

The five scenarios and their timing allowances live in
[docs/TESTING.md](../docs/TESTING.md#end-to-end). They are not repeated here: this file, that
one and `tasks/TT.8-e2e-suite.md` each carried a copy, and they had already drifted.

## `check_night_marker.py`, which is here already

One scenario does exist ahead of TT.8, because T6.4's acceptance needed it: the night
profile's backlight is a window property no browser can see, and the app's only evidence for
it is the `night=` marker.

```bash
python e2e/check_night_marker.py
```

It runs the PC server itself, under a temporary config, and walks the window from day to
night and back — asserting both edges. Both, because either is free to be wrong alone: an app
logging the marker on every refresh passes the first for ever, and one that never cleared its
state passes the first and fails the second. It needs port 8777 free and refuses to start if
something is already listening, because changing that config means a restart and restarting
somebody's running server is not a script's to do.

The marker is emitted on transitions only, like every other marker here, which is why the
window has to be driven rather than waited for. T6.4's task file records the acceptance it
shipped with — `logcat -c && sleep 90 && grep night=on` — and why no correct implementation
could ever have passed it.

## Why this does not read screen state from the OS

`adb shell dumpsys power` filtered for `mWakefulness` is the usual recipe, and it is **not**
documented by Android — the field is known from reading AOSP source and can change without
notice. So the app emits its own markers on the `DeskPanel` logcat tag and this suite asserts on
those. Reasoning in [ADR 0009](../docs/adr/0009-testing-strategy.md).

The markers are a contract, listed in [docs/TESTING.md](../docs/TESTING.md#end-to-end).
Renaming one breaks this suite.
