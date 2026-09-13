# TT.6 — Logcat markers

Size: S · Prereqs: T4.2, T4.3 · Pairs with: T4.4 · Files: `MainActivity.java`, `PcPoller.java`,
`docs/TESTING.md`

Requires: phone (on adb), PC server stoppable

## Goal

Give the E2E suite something reliable to assert on. This is a silent prerequisite for the whole
of TT.8.

Android exposes **no documented way** to read screen state from adb: `dumpsys power` and
`mWakefulness` come from reading AOSP source, not public documentation, and can change between
versions without notice. So the app reports its own state
([ADR 0009](../docs/adr/0009-testing-strategy.md)).

## Steps

1. One tag, `DeskPanel`. Two kinds of marker, and the distinction is the whole design:

   **Transition markers** — emitted only when the state changes, never on every poll. These are
   what the E2E suite asserts on.

   ```java
   Log.i("DeskPanel", "state=online");    // PcPoller,  T4.2
   Log.i("DeskPanel", "state=offline");   // PcPoller,  T4.2
   Log.i("DeskPanel", "screen=wake");     // MainActivity, T4.3
   Log.i("DeskPanel", "screen=sleep");    // MainActivity, T4.3
   Log.i("DeskPanel", "night=on");        // MainActivity, T6.4
   Log.i("DeskPanel", "night=off");       // MainActivity, T6.4
   ```

   **Heartbeat markers** — emitted per cycle, at a bounded rate, because several acceptance
   criteria are "this is still running" and there is no other way to assert that:

   ```java
   Log.i("DeskPanel", "tick=" + epochSeconds);      // the clock is alive,  T2.4
   Log.i("DeskPanel", "ping=" + outcome);           // one poll attempt,    T5.3
   Log.i("DeskPanel", "data=ok" | "data=err");      // one data cycle,      T5.1
   Log.i("DeskPanel", "battery=" + level);          // on broadcast,        T5.4
   ```

   `tick=` is once a minute, not once a second: the point is survival over hours, and a
   per-second line would be the log spam T4.2 forbids.

2. Put the emitting in one small class — `Markers.java` — so every string exists in exactly one
   place. The acceptance greps for that, because a marker duplicated inline is how the E2E
   suite starts passing against a stale copy.
3. Keep these at `Log.i` — they must survive a release build. Do not demote them to `Log.d`.
4. Document the vocabulary in `docs/TESTING.md` and note that it is a contract: renaming one
   breaks the E2E suite, and `T5.3`'s rate assertions depend on the heartbeat cadence.

## Acceptance

Kill the server on the PC, wait, then:

```bash
adb logcat -c && sleep 20 && adb logcat -d -s DeskPanel > /tmp/desk-panel-markers.log
grep -q 'state=offline' /tmp/desk-panel-markers.log
grep -q 'screen=sleep'  /tmp/desk-panel-markers.log
test "$(grep -c 'state=offline' /tmp/desk-panel-markers.log)" -eq 1
```

Start it again, wait, then the same three with `state=online` and `screen=wake`. The count is
the point: each marker appears once per transition, not on every poll.

```bash
! grep -rn 'state=\|screen=' android/app/src/main/java --include=*.java | grep -v 'Markers.java'
```

The strings live in exactly one place. This is what makes the E2E suite's assertions stable
([ADR 0009](../docs/adr/0009-testing-strategy.md)).

## Notes

- **These strings are an API.** TT.8 greps for them verbatim. Renaming one breaks the E2E suite,
  which is why `android/CLAUDE.md` says so.
- Resist adding more markers. Four cover the behaviour; more is noise to grep through.
