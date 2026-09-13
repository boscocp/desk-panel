# End-to-end suite

Drives the real phone over adb. Built in task TT.8.

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

| # | Action | Assertion |
|---|---|---|
| 1 | Server running | `state=online` within 5s |
| 2 | Stop the server | `state=offline` and `screen=sleep` within 20s |
| 3 | Start the server | `state=online` and `screen=wake` within 20s |
| 4 | `/quotes` serving a fixture | Rendered values match |
| 5 | Phone Wi-Fi off 30s, then on | No crash; recovers unaided |

The 20s allowances exist because the offline backoff caps at 15s (T5.3). Tighter windows produce
flaky failures that are not bugs.

## Why this does not read screen state from the OS

`adb shell dumpsys power` filtered for `mWakefulness` is the usual recipe, and it is **not**
documented by Android — the field is known from reading AOSP source and can change without
notice. So the app emits its own markers on the `DeskPanel` logcat tag and this suite asserts on
those. Reasoning in [ADR 0009](../docs/adr/0009-testing-strategy.md).

Those four markers are a contract. Renaming one breaks this suite.
