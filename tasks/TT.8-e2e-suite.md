# TT.8 — `e2e/run_e2e.py`

Size: L · Prereqs: TT.6, T5.1 · Files: `e2e/run_e2e.py`, `e2e/README.md`

## Goal

One command that exercises the real behaviour on the real phone and exits 0 or non-zero.

## Steps

1. `e2e/run_e2e.py`, standard library only. It orchestrates: start and stop the server, read
   `adb logcat`, assert.
2. Helper: `wait_for_marker(marker, timeout)` — stream `adb logcat -s DeskPanel` in a
   subprocess, return `True` on match, `False` on timeout. Clear the buffer with `adb logcat -c`
   before each scenario or you will match stale lines.
3. The five scenarios:

   | # | Action | Assertion |
   |---|---|---|
   | 1 | Server running | `state=online` within 5s |
   | 2 | Stop the server | `state=offline` and `screen=sleep` within 20s |
   | 3 | Start the server | `state=online` and `screen=wake` within 20s |
   | 4 | `/quotes` serving a fixture | Rendered values match (delegate to TT.7) |
   | 5 | Phone Wi-Fi off 30s, then on | No crash in logcat; recovers unaided |

   The 20s allowances exist because T5.3's backoff caps at 15s. Tighter windows produce flaky
   failures that are not bugs.
4. `dumpsys power` may be used as an **optional corroborating check**, in one clearly named
   function with a comment saying it is AOSP-derived and undocumented. If it disagrees, print a
   warning — **do not fail the run**.
5. Print a per-scenario summary and exit non-zero if any scenario failed.
6. `e2e/README.md`: what each scenario covers, and the prerequisites (phone on adb, app
   installed, server configured).

## Acceptance

```bash
python e2e/run_e2e.py
echo $?      # 0
```

Then deliberately break something — stop the server mid-run — and confirm it exits non-zero
with a message naming the scenario that failed.

## Notes

- Never assert on `mWakefulness` as a **primary** signal. That is the whole point of TT.6 and
  [ADR 0009](../docs/adr/0009-testing-strategy.md).
- Scenario 5 needs `adb shell svc wifi disable` / `enable`, which may require permissions MIUI
  withholds. If it does, mark scenario 5 as manual and say so in the README rather than leaving
  a test that cannot pass.
- Slow by nature — over a minute end to end. It is not part of `make check` for that reason.
