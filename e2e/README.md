# End-to-end suite

Drives the real phone over adb. The suite itself is built in task TT.8; this file describes
it ahead of time, which is why nothing here runs yet.

## Prerequisites

- Phone reachable over adb (see `docs/INSTALL-PHONE.md`)
- The app installed, with MIUI autostart and battery exemption already granted
- `server/config.json` present and valid

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

## Why this does not read screen state from the OS

`adb shell dumpsys power` filtered for `mWakefulness` is the usual recipe, and it is **not**
documented by Android — the field is known from reading AOSP source and can change without
notice. So the app emits its own markers on the `DeskPanel` logcat tag and this suite asserts on
those. Reasoning in [ADR 0009](../docs/adr/0009-testing-strategy.md).

The markers are a contract, listed in [docs/TESTING.md](../docs/TESTING.md#end-to-end).
Renaming one breaks this suite.
