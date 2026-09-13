# TT.6 — Logcat markers

Size: S · Pairs with: T4.4 · Files: `MainActivity.java`, `PcPoller.java`,
`docs/TESTING.md`

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

```bash
adb logcat -c && adb logcat -s DeskPanel
```

Kill the server: `state=offline` then `screen=sleep`. Start it: `state=online` then
`screen=wake`. Each appears once per transition, not repeatedly.

## Notes

- **These strings are an API.** TT.8 greps for them verbatim. Renaming one breaks the E2E suite,
  which is why `android/CLAUDE.md` says so.
- Resist adding more markers. Four cover the behaviour; more is noise to grep through.
