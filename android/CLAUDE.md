# Android layer

Java, not Kotlin — deliberately (ADR 0001). One Activity, one WebView, no Jetpack Compose.
Package `dev.bosco.deskpanel`. `minSdk 26`, `compileSdk`/`targetSdk 36`.

There is also exactly one service, `PanelService`, and it is not a violation of the line above:
that rule is about the UI, and this is not a second screen. **Do not fold the poll loop back
into the Activity.** The screen going out stops the Activity, so a loop living there switches
itself off at precisely the moment it would have to notice the PC returning — `screen=wake`
then can never fire. The whole reasoning, including why a wake lock is affordable on this rig
and what has to change if that stops being true, is in
[ADR 0014](../docs/adr/0014-poll-loop-outlives-the-screen.md).

## Rules specific to this layer

- **Never add a `fetch` to the web assets.** Network belongs here, in Java. See invariant 1 in
  the root `CLAUDE.md`.
- **Never set `MIXED_CONTENT_ALWAYS_ALLOW`.** The official guidance advises against it, and
  with native polling there is nothing to allow.
- **Never copy `web/` into `assets/`.** `build.gradle.kts` points `assets.srcDirs` at
  `../../web`; one copy of those files, always.
- **Cleartext stays pinned.** `res/xml/network_security_config.xml` permits `http://` for the
  PC's IP and nothing else. Widening it to `base-config` defeats the purpose.
- **Keep logic out of Android classes.** Anything worth testing — the online/offline state
  machine, backoff timing, JSON shaping — goes in a plain class like `PcState.java` with no
  Android imports, so `./gradlew test` covers it on the JVM without a device.
- **Emit logcat markers on every state transition**, and take every marker string from
  `Markers.java` — never write one inline. `state=online`, `state=offline`, `screen=sleep`,
  `screen=wake` and the rest live there once, and the TT.6 acceptance greps that no copy exists
  anywhere else under `main/java`, because a duplicated marker is how the E2E suite starts
  passing against a stale string. The suite asserts on these because Android exposes no
  documented way to read screen state from adb (ADR 0009). Renaming or dropping one breaks it.

## Build and test

```bash
docker compose -f docker/compose.yml run --rm build ./gradlew assembleDebug
docker compose -f docker/compose.yml run --rm build ./gradlew test    # JVM, no device
./gradlew connectedAndroidTest                                        # needs the phone
```

`connectedAndroidTest` does not run in CI — it needs real hardware.

## Files that several tasks touch

`MainActivity.java` is edited by more than one task across different sessions. Before editing
it, check `tasks/STATUS.md` for which of those have already landed, so you extend the current
state instead of reverting someone else's work.
