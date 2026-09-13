# TT.5 — `PcState` extracted and tested on the JVM

Size: M · Prereqs: T2.1 · Pairs with: T4.2, T5.3 · Files:
`android/app/src/main/java/dev/bosco/deskpanel/PcState.java`,
`android/app/src/test/java/dev/bosco/deskpanel/PcStateTest.java`

## Goal

Test the online/offline machine and the backoff schedule without a device, an emulator or a
clock to wait on.

## Steps

1. `PcState.java` must have **no Android imports**. No `Context`, no `Log`, no `Handler`. It is
   a plain Java class, which is what lets `./gradlew test` run it on the JVM in a second.
2. It owns:
   - the current state, and whether a transition just occurred
   - the consecutive-failure count
   - `nextIntervalMs()` — 2000 online; 2000, 4000, 8000 capped at 15000 offline
   - a reset to the online cadence on first success
3. Add JUnit as a `testImplementation` dependency.
4. `PcStateTest.java` covering: first success, first failure, backoff growth, the 15s cap,
   recovery resetting the interval, and transitions firing exactly once rather than on every
   poll.
5. `PcPoller` keeps no state of its own — it asks `PcState` what to do and when.

## Acceptance

```bash
docker compose -f docker/compose.yml run --rm build ./gradlew test
```

Exit code 0, and it finishes in seconds. If a test sleeps, the timing is in the wrong place —
`nextIntervalMs()` returns a number; the test asserts on the number, it does not wait for it.

```bash
! grep -q "android\." android/app/src/main/java/dev/bosco/deskpanel/PcState.java
```

`PcState` must stay free of the Android framework or it cannot be tested on the JVM. Negated,
because a bare `grep` exits 1 exactly when the file is clean.

## Notes

- This is the payoff for keeping Android out of the logic: backoff behaviour that would take
  minutes to observe on a device is asserted instantly here.
- Transition-fires-once is the case most likely to be wrong, and the one that causes log spam
  and repeated screen toggling.
