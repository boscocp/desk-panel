# TT.7 — Espresso-Web assertions

Size: M · Pairs with: T5.1 · Files:
`android/app/src/androidTest/java/dev/bosco/deskpanel/PanelRenderTest.java`

Requires: phone (on adb)

## Goal

Prove that data arriving from native actually reaches the DOM and renders — the one seam that
unit tests on either side cannot cover.

## Steps

1. Add `androidx.test.espresso:espresso-core` and `espresso-web` as `androidTestImplementation`.
2. Launch the activity with an `ActivityScenarioRule`.
3. Inject a known payload by calling `window.onData()` with fixture values, rather than waiting
   on a real server — the test must be deterministic.
4. Assert with Espresso-Web `onWebView()` and `withElement(findElement(Locator.ID, ...))` that
   the rendered text matches the fixture.
5. Cover both states: a populated panel with data, and the blacked-out panel after
   `window.onPcState(false)`.

## Acceptance

```bash
adb devices | grep -qw device
make connected
```

Exit code 0 with the phone connected. This does **not** run in CI — it needs real hardware.

`./gradlew connectedAndroidTest` printed bare in the original could not work: the JDK lives
only inside the container ([ADR 0003](../docs/adr/0003-containerized-toolchain.md)) and the
container cannot see the phone's adb socket. `make connected` is the target that resolves it,
by running Gradle in the container against the host's adb server over TCP. Defining that
target is part of this task, and `STATUS.md`'s open question about adb-from-container is
answered here.

## Notes

- Espresso-Web needs JavaScript enabled on the WebView, which T2.2 already does.
- Give the elements you assert on stable `id` attributes. Asserting on position or class makes
  the test break every time T6.1 is touched.
- If it is flaky, the usual cause is asserting before the WebView finishes loading. Use an
  idling resource rather than a sleep.
