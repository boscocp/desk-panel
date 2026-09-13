# TT.8 — `e2e/run_e2e.py`

Size: L · Prereqs: TT.6, T5.1 · Files: `e2e/run_e2e.py`, `e2e/README.md`

Requires: phone (on adb), PC server stoppable

## Goal

One command that exercises the real behaviour on the real phone and exits 0 or non-zero.

## Steps

1. `e2e/run_e2e.py`, standard library only. It orchestrates: start and stop the server, read
   `adb logcat`, assert.
2. Helper: `wait_for_marker(marker, timeout)` — poll `adb logcat -d -s DeskPanel` until the
   marker appears or the timeout expires, and clear the buffer with `adb logcat -c` before each
   scenario or you will match stale lines. `-d` dumps and exits; streaming without it is how a
   suite hangs forever on a marker that never arrives.
3. The five scenarios, their assertions and their timing allowances are in
   [docs/TESTING.md](../docs/TESTING.md#end-to-end), which is the single source. This file,
   that one and `e2e/README.md` each carried a copy and they had already drifted on scenario 5.
   Implement what is there; if a scenario needs to change, change it there first.

   Scenario 4 delegates the render assertion to TT.7, so TT.7 is a prerequisite of a complete
   run — not of writing the suite.
4. `dumpsys power` may be used as an **optional corroborating check**, in one clearly named
   function with a comment saying it is AOSP-derived and undocumented. If it disagrees, print a
   warning — **do not fail the run**.
5. Print a per-scenario summary and exit non-zero if any scenario failed.
6. `e2e/README.md` already exists and describes the suite ahead of time. Update it rather than
   creating it, and keep it pointing at `docs/TESTING.md` for the scenario table.

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
