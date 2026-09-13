# TT.6 — Logcat markers

Size: S · Pairs with: T4.4 · Files: `MainActivity.java`, `PcPoller.java`,
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

1. One tag, `DeskPanel`. Exactly four markers, emitted **only on transition**, never on every
   poll:

   ```java
   Log.i("DeskPanel", "state=online");
   Log.i("DeskPanel", "state=offline");
   Log.i("DeskPanel", "screen=wake");
   Log.i("DeskPanel", "screen=sleep");
   ```

2. Put the emitting in one small method so the strings exist in exactly one place.
3. Keep these at `Log.i` — they must survive a release build. Do not demote them to `Log.d`.
4. Document the four markers in `docs/TESTING.md` and note that they are a contract.

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
