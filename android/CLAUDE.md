# Android layer

Java, not Kotlin — deliberately (ADR 0001). One Activity, one WebView, no Jetpack Compose.
Package `dev.bosco.deskpanel`. `minSdk 26`, `compileSdk`/`targetSdk 36`.

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
- **Emit logcat markers on every state transition**: `Log.i("DeskPanel", "state=online")`,
  `state=offline`, `screen=sleep`, `screen=wake`. The E2E suite asserts on these, because
  Android exposes no documented way to read screen state from adb (ADR 0009). Renaming or
  dropping a marker breaks the E2E suite.

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
