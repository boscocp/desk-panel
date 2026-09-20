# desk-panel

## Project Goal
- Turn a spare Redmi Note 10 (Android 12, MIUI 14) into a landscape desk panel showing a
  clock, B3 stock quotes, crypto and FX rates, and weather, in a cyberpunk-neon skin.
- The panel is visible **only while the Windows PC is powered on and logged in**. When the PC
  goes away the phone screen sleeps. That behaviour is the whole point of the project.

## The three invariants (breaking these silently breaks the design)
1. **JavaScript never calls `fetch`.** All network I/O happens in native Java. The WebView is
   served from `https://appassets.androidplatform.net/`, so talking to a `http://` LAN address
   from JS would be mixed content. Native polling sidesteps it; keep
   `MIXED_CONTENT_NEVER_ALLOW`.
2. **The PC server is the login signal.** It is launched by, and dies with, the **graphical
   session of a human user** — a Scheduled Task with an "At log on" trigger on Windows, a
   systemd user unit bound to `graphical-session.target` on Linux, a LaunchAgent with
   `LimitLoadToSessionType=Aqua` on macOS. So "it answers" means "the user is logged in".
   Never move it to anything of system scope — a Windows Service, a systemd system unit, a
   LaunchDaemon, `@reboot`, **or a Docker container**. Each answers without a login and reports
   the wrong thing. A systemd *user* unit on `default.target` is in that class too, and looks
   like it is not: see [ADR 0010](docs/adr/0010-login-signal-is-session-scoped.md).
3. **Screen state is driven by PC state, never by a timeout.** Online: hold
   `FLAG_KEEP_SCREEN_ON`. Offline: clear it and let Android sleep, then wake with
   `setTurnScreenOn(true)` + `setShowWhenLocked(true)`. Fallback if MIUI misbehaves:
   `screenBrightness = 0f` plus a black render (see ADR 0005).

## Layout
- `web/` — the panel UI. Plain HTML/CSS/JS, no framework, no build step. Packaged as APK
  assets; `android/app/build.gradle.kts` points `assets.srcDirs` here, so there is only ever
  one copy of these files.
- `web/js/format.js` — pure functions only. This is what the tests exercise.
- `android/` — one Activity, one WebView, Java. See `android/CLAUDE.md`.
- `server/` — Python 3.13, standard library only. See `server/CLAUDE.md`.
- `e2e/run_e2e.py` — end-to-end scenarios driving the real phone over adb.
- `docs/adr/` — why things are the way they are. Read before arguing with a decision.
- `reasonix.toml` — permissions for the local-model agent; the twin of `.claude/settings.json`,
  which Reasonix does not read. Change one, change the other. See `docs/LOCAL-MODELS.md`.
- `tasks/` — one file per unit of work. `tasks/STATUS.md` is the index.

## Commands
```bash
make check                                       # everything that needs no phone
python -m unittest discover -s server/tests -t . # server
node --test "web/test/**/*.test.js"              # web
docker compose -f docker/compose.yml run --rm build ./gradlew test          # Android, JVM
docker compose -f docker/compose.yml run --rm build ./gradlew assembleDebug # APK
python e2e/run_e2e.py                            # end-to-end, needs the phone
python server/server.py                          # run the PC server in the foreground
```
The Android toolchain lives **only inside the Docker image**. Never install the JDK, the
Android SDK or Android Studio on the Windows host — keeping the host clean is a project
requirement, not a preference (ADR 0003).

## How to resume work
1. Read `tasks/STATUS.md` and take the first task that is not `done`.
2. Read only that task file. Each one is self-contained by design — do not read the whole
   repository to get oriented.
3. Execute it, run its acceptance command, and only then mark it `done` in `STATUS.md`.
4. A coding task is not finished until its paired test task is green.

Every acceptance criterion is a command with an exit code. If you find yourself judging a task
by looking at output, the task file is wrong — fix the task file.

## Conventions
- English everywhere: code, comments, docs, commit messages.
- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- **Commit messages carry no Claude attribution and no `Co-Authored-By` line.**
- Secrets never enter git: `server/config.toml` (and the older `server/config.json`) and
  `*.keystore` are gitignored. The brapi
  token lives on the PC and is proxied, so it never ships inside the APK.
- Changing tickers, the city or the theme must never require rebuilding the APK — it is server
  config, in `server/config.toml`, whose committed example documents every legal value.

## Traps that have already cost time
- **MIUI kills background apps.** `FLAG_KEEP_SCREEN_ON` stops the screen sleeping; it does not
  stop the battery manager freezing the Activity. Autostart and the battery exemption are
  manual per-device toggles (`docs/INSTALL-PHONE.md`).
- **The PC needs a static DHCP reservation.** `network_security_config.xml` pins the PC's IP;
  if it changes, the app reports "offline" forever and looks like a bug.
- **Screen state is not readable from adb in any documented way.** `dumpsys power` /
  `mWakefulness` come from reading AOSP source, not public docs. The app therefore emits its
  own logcat markers (`state=`, `screen=`) and the E2E asserts on those (ADR 0009).
- **The phone runs on battery whenever the PC is off**, assuming ErP Ready is disabled in the
  BIOS as `docs/DEVICE-CARE.md` recommends. Sloppy polling drains it overnight.
