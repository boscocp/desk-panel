# Status

The index. Take the first task that is not `done`, read **only** that task file, execute it,
run its acceptance command, then come back and update this table.

A coding task is not `done` until its paired test task is green.

**"Execute the next wave" is a standing instruction**, not a question: take what the latest
`## Resuming after (wave N)` section recommends, run it to the merge, and stop only for
something critical. The protocol is in [`CLAUDE.md`](../CLAUDE.md); what this loop has cost and
caught, wave by wave, is in [`docs/LEARNING-REPORT.md`](../docs/LEARNING-REPORT.md), and each
wave leaves a note in [`docs/harness-notes/`](../docs/harness-notes/) that `make lint-notes`
requires.

Legend: `todo` · `wip` · `blocked` · `done`

Two conventions the task files now carry, both enforced by `make lint-tasks`:

- **`Requires:`** in the header says what a task needs beyond a checkout — the phone, a
  reachable PC, a dark room. The `verifier` agent uses it to say "not verified" instead of
  guessing.
- **`## Acceptance`** is commands only. Anything a human has to look at lives under
  `## Manual check`, and is not pretended to have an exit code.

Rows without a task file — T0.0, T0.2, T0.3, T0.4 — are bootstrap work, recorded for history.
`/task` and the `verifier` cannot address them; that is expected, not a gap.

## Phase 0 — Foundation

| # | Task | State | Notes |
|---|---|---|---|
| T0.0 | Git identity and repository creation | done | Bootstrap session, 2026-09-13 |
| T0.1 | Containerised Android toolchain | done | 2026-09-14. JDK 21.0.5 + SDK 36, 1.45 GB image; host still has no `java`. Given to the local model first and it failed twice — `docs/harness-notes/2026-09-14-T0.1.md` |
| T0.2 | Repository skeleton, README, gitignore, gitattributes | done | Bootstrap session |
| T0.3 | The nine ADRs | done | Bootstrap session |
| T0.4 | CLAUDE.md files, STATUS.md, `.claude/` | done | Bootstrap session |
| T0.5 | Spec remediation | done | 28 of 36 acceptance blocks were not commands. `make lint-tasks` keeps it that way |
| T0.6 | **Two-agent setup: `reasonix.toml`, model pinning** | done | 2026-09-23, wave 21. All five acceptance commands exit 0. `reasonix.toml` now pins `default_model` and a `[[providers]]` block, so the provider is no longer in an untracked `~/.reasonix/config.toml`; `context_window = 131072` matches the model's own Modelfile. `git commit`/`git push` moved from allow to **deny** (ADR 0011). `scripts/check_permission_parity.py` compares the twins by command *family* — `Bash(make check)`, `Bash(make check *)` and `Bash(make check:*)` are one rule — and is wired into `make check` as `lint-permissions`; it reports a stale exemption as loudly as a new drift. It found 21 real asymmetries on first run, all declared. Two things were **measured, not read**: `forbid_read` matches literal paths only (a `*.keystore` entry let `cat` through; the spelled-out name returned `Permission denied`), which is why the keystore is listed by name and Claude's glob deny is an intentional asymmetry; and there is no `read-only` permission mode — `plan` is the read-only one and it **refuses to run headless**, so the end-to-end line uses `manual`. The task file said `read-only` and was fixed. `curl`, `keytool`, `adb shell`, `adb install`, `make lint-*`, `make connected` and `python scripts/*.py` were missing from both files and are now in both — at the **prefix the acceptance blocks use**, not as command families, which is the review's doing: `adb shell *` reaches `pm uninstall` and `keytool *` destroys the signing key, and both losses cost an uninstall and the MIUI grants T2.4 obtains by hand. **Six review findings, all applied.** The two structural ones were caught by mutation, not by reading: exemptions keyed by rule alone meant deleting the `git commit` deny that ADR 0011 rests on still exited 0, so they are keyed by `(list, rule)` now and the marker names its list; and the marker matched anywhere in a comment, so the header sentence *explaining* it was already being parsed as an exemption block. A third is the gate's own blind spot: `make lint-permissions` was allowed by neither file, and a parity check cannot see a rule missing from both sides |

## Phase 1 — Web in isolation (needs only Chrome)

| # | Task | State | Notes |
|---|---|---|---|
| T1.1 | Clock in plain HTML/JS | done | 2026-09-16. Brought from `harness/t1.1-accepted` |
| TT.1 | Extract `format.js` + node:test | done | 2026-09-16. 16 tests, `node --test` green; purity grep passes. `isNight` takes `"HH:MM"`, the shape config ships |
| T1.2 | `mock.js` fixtures | done | 2026-09-16. `app.js` now renders quotes/fx/crypto/weather/battery/stale via `format.js`; mock guarded behind `file:` + `__nativeBridge` check in `index.html` |

## Phase 2 — Android skeleton

| # | Task | State | Notes |
|---|---|---|---|
| T2.1 | Minimal Gradle project in Java | done | 2026-09-16. Java app module (`dev.bosco.deskpanel`), `compileSdk`/`targetSdk 36`, `minSdk 26`, Java 17 bytecode. Gradle 9.7.1 + AGP 9.4.0, wrapper pinned with a `distributionSha256Sum`. Real wrapper lives in `android/` (`git update-index --chmod=+x android/gradlew` per the task); a thin root-level `./gradlew` delegates into it so the Makefile's bare `./gradlew` keeps working from the repo root. `assembleDebug` copies the APK to `out/` via `androidComponents.onVariants` + `afterEvaluate` (the `assemble<Variant>` task isn't registered yet inside `onVariants`). `MainActivity` is an empty `FrameLayout`; assets point at `../../web`, not a copy. Both acceptance commands exit 0 |
| T2.2 | WebView + WebViewAssetLoader | done | 2026-09-16. 🏁 **Milestone A — the panel is on the phone.** All ten acceptance lines exit 0, run under `bash`. `MainActivity` serves `web/` through `WebViewAssetLoader` at `https://appassets.androidplatform.net/assets/index.html` with `MIXED_CONTENT_NEVER_ALLOW` and `androidx.webkit:webkit:1.12.1`; `onPageFinished` logs `panel=rendered clock="HH:MM:SS"` read out of the live DOM, because a WebView that draws nothing also logs nothing and the negated error grep passes just as happily on a black screen. Confirmed past the greps with a screencap, twice: cyan neon on the near-black purple ground, clock and date painted, and the five section cards drawn as empty outlines — which is itself the proof that `mock.js` stayed inert over the `https` origin, since the `file:` guard in `index.html` held. **Known-good but not yet pretty: in portrait the clock and date overflow the viewport horizontally.** Only the minutes are on screen; hours and seconds are clipped off both edges, and the date renders as "eira, 16 de setembro". The CSS is written for landscape, which T2.3 has not set yet, so this is expected rather than a regression — but it has a nasty side effect worth knowing about before T2.3 lands: two screencaps five seconds apart are **byte-identical**, because the only visible digits are the ones that change once a minute. The panel looks frozen when it is not. Title, status and navigation bars are all still visible; immersive is T2.3's. Debug and release now differ — the acceptance builds and installs `out/desk-panel-release.apk`, so the device carries the release key from its first install, exactly as T7.1 intended. The MIUI wall cost most of the session: `INSTALL_FAILED_USER_RESTRICTED` three times, with user 0's restriction lists completely empty (`dumpsys user`), so the refusal came from MIUI's own package-manager hook rather than AOSP. It cleared only after a human toggled Developer options → "Install via USB" off and back on; "USB debugging (Security settings)" alone was not enough. That toggle also gates `adb shell input`, so while it was off the phone could not even be woken from the host. `Requires:` now records all of it. The acceptance block was rewritten twice — see the correction section in the task file, and the note below |
| T2.3 | Keep screen on, landscape, immersive | done | 2026-09-16. All six acceptance lines exit 0, run verbatim under `bash -euxo pipefail`. **The `sleep 600` criterion was replaced**: a fixed wait asserts nothing unless the device's screen timeout happens to be shorter than it, so it now reads `screen_off_timeout` off the device and waits twice it plus slack — 135s here against a timeout of 60000, and still a real assertion on a phone set to "never". `test "$TIMEOUT_MS" -gt 0` guards it, because `settings get` prints `null` for an unset key and an unset timeout must fail the criterion rather than shrink the wait to 15s; proved fail-closed (`test: null: integer expected`, exit 2). That guard also subsumed the old `settings get ... > /dev/null` line, which only asserted that the command ran, so the block went from four lines to six and lost one. The 600s version was also run in full once, before the replacement, and passed. `android:screenOrientation="landscape"` in the manifest; `FLAG_KEEP_SCREEN_ON` behind a single `setKeepScreenOn(boolean)` so T4.4 has one place to clear it, and no timer anywhere; immersive via `WindowCompat.setDecorFitsSystemWindows(false)` + `WindowInsetsControllerCompat.hide(systemBars())` with `BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE`, re-applied in `onWindowFocusChanged` because transient bars come back on every focus regain. `androidx.core:core:1.13.1` made explicit — it arrived transitively through webkit, but the immersive code is ours. Two things `dumpsys` did not say and the screencap did. First, hiding the bars is not full screen on this device: the window still stopped at the camera cutout and left a **93px black strip down the left edge**, fixed with `LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES` (guarded at API 28; `minSdk` is 26). That also bought the clock room — the viewport went from 839 to 872 CSS px, and the clock needs 832. Second, the default activity theme still drew a title strip above the panel, so the activity takes `@android:style/Theme.Material.NoActionBar`, which kills that and gives a dark window background instead of a white pre-paint flash. **T2.2's portrait overflow is gone with no CSS change**: `17:44:48` renders in full, hours and seconds included, and the date reads `quarta-feira, 16 de setembro de 2026` end to end. The byte-identical-screencap symptom is gone with it — seconds are on screen now, and two captures 5s apart differ. **Still not fitting vertically, and deliberately left to T6.1**: the landscape viewport is only ~392 CSS px tall, `style.css` spends 160px of it on the clock alone, and the fifth card (battery) is clipped off the bottom. Making that fit means re-proportioning the page, which is T6.1's `full neon layout`, not a fitting tweak — and the cards are empty outlines until T3.3/T4.x fill them. Handed over and since fixed there: the clock is 60px now. One trap paid for here: `adb install -r` kills the app, drops its window and with it `FLAG_KEEP_SCREEN_ON`, so a reinstall part-way through the 600s wait silently invalidates it. Do not touch the device once that clock is running. Re-verified after `9063e42` moved the manifest to `sensorLandscape`: rebuilt, reinstalled, and the whole block re-run green against that APK (`aapt2` reports `screenOrientation=6`). The rotation grep held — the phone now settles on `ROTATION_270` where the pinned `landscape` gave `ROTATION_90`, which is exactly the case `ROTATION_(90\|270)` was written for. The cutout fix survives it: sampling the screencap, x=0 and x=2399 were both `(10, 1, 24)` = `#0A0118`, the panel's own ground, and the leftmost content pixel is at x=176 against a cutout ending at x=93, so nothing sits under the notch. **Do not re-run that pixel check — `b2c0ded` re-cut the ground to `#000000` and it no longer discriminates**: a filled cutout and an unfilled one are now the same black, so the check passes either way. Read the window instead, which is palette-independent — but **scope it to our own window**: `dumpsys window windows` lists every window on the device, and `com.miui.home`'s launcher also declares `shortEdges`, so an unscoped grep passes even when our activity is at `default`. Verified: the unscoped form exits 0 against MIUI Home alone. The scoped form is `adb shell dumpsys window windows | tr -d '\r' | awk '/Window #.*dev\.bosco\.deskpanel/{f=1} f&&/layoutInDisplayCutoutMode=/{print;exit}' | grep -q 'layoutInDisplayCutoutMode=shortEdges'`, which takes the first mode after our own window line — `mAttrs` is several lines below it, not the next one, so `grep -A1` finds nothing. Proved to discriminate: it accepts `shortEdges` and rejects `never`, `always` and `default`. `dumpsys window | grep mDisplayCutout` corroborates the geometry the fix is against — `insets=Rect(93, 0 - 0, 0)`, one bounding rect at `Rect(0, 503 - 93, 577)`. Raised as an open risk here and **since closed by `9134929`**: with no `android:configChanges` on the activity a 180° flip might have relaunched it and reloaded the WebView, which would have been invisible in a screenshot and shown up only as a clock that silently restarted. Measured rather than assumed — the pid stayed 27861 across a flip from `ROTATION_270` to `ROTATION_90` and `panel=rendered` stayed at one occurrence, so nothing the activity would have to declare actually changes and no `configChanges` is needed |
| T7.1 | Release keystore and signing | done | 2026-09-16. Keystore created by a human; `build.gradle.kts` signs `release`, falling back to the debug key when the signing values are absent so a fresh clone still builds. APK at `out/desk-panel-release.apk`; `apksigner --print-certs` confirms the release DN, not `CN=Android Debug`. All six acceptance commands exit 0. Install-over check still manual. **Amended by T2.5**: the signing values moved from `keystore.properties` into `.env` under `KEYSTORE_FILE`/`KEYSTORE_PASSWORD`/`KEY_ALIAS`/`KEY_PASSWORD` (ADR 0013); the fallback behaviour is unchanged, and the acceptance block was re-run green after the move |
| T2.5 | **`.env` for build-time local config** | done | 2026-09-16. All ten acceptance commands exit 0, run verbatim under `bash`. `.env.example` committed with empty values and the token prohibition written beside the keys; `.env` was already in `.gitignore` from T0.2, so that step was a verification rather than an edit. `build.gradle.kts` parses `../.env` itself — no shell wrapper, because sourcing it would put the signing passwords into the environment of every process the build spawns. **The substitution is on a generated copy, never on the tracked file.** `src/main/res` is copied to `build/generated/netsec/res` with the placeholder replaced, and that generated tree *replaces* `src/main/res` as the module's only res source dir — two source dirs carrying the same resource name is a duplicate-resource error, and there is no ordering inside one source set that makes one win. `preBuild` depends on the copy. Verified both ways, which is the one property no acceptance command proves: `git diff` leaves `network_security_config.xml` untouched with `192.168.1.100` still in it, and `aapt2 dump xmltree` on `out/desk-panel-release.apk` decodes the packaged resource to `T: '192.168.15.3'`. The packaged path is **not** `res/xml/network_security_config.xml` — `optimizeReleaseResources` shortens resource paths, so it is `res/8G.xml`, and `aapt2 --file res/xml/...` answers `failed to find file` on a perfectly correct APK. Find it by grepping the extracted `res/*.xml` for the address; note the string pool flips between UTF-8 and UTF-16 depending on content, so search both (`strings -a` and `strings -a -el`). Every build prints one line at configuration time, not from a task action, so it survives an all-up-to-date rerun: `desk-panel: cleartext pinned to 192.168.15.3 (from .env)`. **A fresh clone builds**, tested rather than argued: the branch was cloned into a scratch directory (`.env` is gitignored, so the clone genuinely lacks one), the two changed files copied in, and `assembleRelease` there exits 0, prints the placeholder variant of the line, and packages `192.168.1.100`. The real `.env` was never moved or renamed. A malformed `PC_IP` fails the build with the offending value rather than generating a corrupt XML — an empty or absent one is the documented fallback, a typo is not. **Signing moved out of `keystore.properties` into `.env`** (`KEYSTORE_FILE`, `KEYSTORE_PASSWORD`, `KEY_ALIAS`, `KEY_PASSWORD`), behaviour identical to T7.1's: all four present means release signing, anything missing falls back to debug. T7.1's file is amended, and its acceptance still guards `keystore.properties` too, since a machine predating this may still have one. **One human step is outstanding and it is not optional**: no agent may read `keystore.properties`, so the four signing values are still empty in the local `.env` and this machine is currently producing a *debug-signed* `desk-panel-release.apk`, which Android will refuse to install over the release-signed build already on the phone. Copy them across, delete the old file, and the build says so on its second line. That second line — `desk-panel: release signing (from .env)` / `desk-panel: debug signing (…)` — is the one thing here the task file did not ask for, added because this migration is exactly what makes a silent fallback newly likely on a machine that had release signing working. Manual check half done: `adb shell ping -c 3 192.168.15.3` from the phone is 3/3, 0% loss, across subnets (phone on `192.168.3.100`). The panel-stops-reporting-offline half waits on T4.2 |
| T2.4 | MIUI smoke test: autostart, battery, reboot | blocked | 2026-09-16. Needs the phone on adb: reboots it and asserts MIUI autostart, battery whitelist |

## Phase 3 — Python server (parallel with phase 2)

| # | Task | State | Notes |
|---|---|---|---|
| T3.1 | `/ping` | done | 2026-09-16. `server/server.py` + `server/probe.py`. Went blocked when T3.2 made a missing config fatal, green again once `config.json` was seeded — no T3.1 code changed either way |
| T3.2 | Config loading | done | 2026-09-16. Pure `load_config` with defaults; hard fail on a missing `config.json`. All four acceptance commands exit 0 |
| T3.3 | `/quotes` proxy | done | 2026-09-19. **Subtask 0 answered by asking the API, not the docs** — which describe the crypto and currency endpoints without giving their shapes. Measured: `/api/v2/stocks/quote?symbols=PETR4,VALE3,ITUB4` and the legacy `/api/quote/...` both 200 without a token; `/api/v2/crypto` and `/api/v2/currency` both **401 MISSING_TOKEN**, and `config.json` carries an empty token. So brapi covers stocks here and nothing else, and the task file's pre-approved fallback is what ships: Binance for crypto, AwesomeAPI for FX, both key-free. Three modules named for three upstreams — a `providers_brapi.py` calling Binance would be a lie in the one place a reader can check. brapi serves **two response shapes** (v2 nests under `data`, legacy is flat) and both answered 200 the same day, so `normalise` reads either; the free tier is the part of an API most likely to move and the failure it produces is an empty panel. Three traps pinned by tests: Binance and AwesomeAPI send every number as a **string**; a currency pair is spelled four ways between config and panel (`USD-BRL`, `USD-BRL`, `USDBRL`, `USD/BRL`) and `normalise` is the only place any may appear; and one cache covers all three markets, so a single upstream failing marks the whole payload stale — honest, since something on the panel is then older than it looks. `curl -sf /quotes | python -m json.tool` exits 0 with every configured symbol |
| T3.4 | `/weather` proxy | done | 2026-09-19. Geocode once and cache the coordinates for the life of the process; forecast on `weather_interval_s`. All three acceptance commands exit 0, `probe.py` gaining the `--expect-json-keys` it needed. **The `daily` arrays are a week, not a day**, and the task file's warning is about which index: without the `timezone` parameter the days cut on UTC boundaries, so after 21:00 in São Paulo index 0 is tomorrow and the panel shows tomorrow's high as today's — a wrong number, not an error. Two defences instead of one: the timezone comes from config (never a literal), and `normalise` finds the day matching `current.time` rather than trusting index 0, so a mismatch costs the min/max instead of silently shifting them. Missing values are `None`, never `0` — zero is a real temperature in most of the world, so a zero standing in for no-data is a lie the panel cannot detect. The city shown is the **resolved** name (`Sao Paulo` in, `São Paulo` out), which is how a human notices they geocoded the wrong Springfield. Manual check: 24°C, 15.5–26.1, code 2, on a September afternoon in São Paulo |
| T3.5 | Login-scoped autostart: contract + verifier | done | 2026-09-16. `server/verify_login_scope.py` + `server/fixtures/login_scope/`. No installer here — T3.8/T3.9/T3.10 still `todo`. `probe.py` was left alone: it shipped with T3.1 and the login-scope work needed no flag it lacks. Every check is a pure function over captured text (`parse_schtasks_xml`, `parse_systemctl_show`, `parse_launchctl_print`, `parse_list_dependencies`, `parse_launchagent_plist`, `detect_autologin`, `detect_system_scope`, `detect_wsl`, `detect_container`) with command execution in a thin shell, so `--self-test` exercises all three platforms from fixtures on one box — 89 cases after T3.8's amendments, and macOS is checkable without a Mac (TT.10's groundwork). **Fails closed**: exit 0 all pass, 1 a real failure, 2 could-not-tell, and a missing command or unreadable file produces 2, never 0. Proved twice — `PATH=/nonexistent` gives 2, and `docker run python:3.13-slim` gives 1 on `not-container` with everything else unknown. Linux fixtures are real captures from this machine (a `desk-panel.service` user unit was installed, enabled, captured in both the good and the `default.target` shapes, then removed); Windows and macOS fixtures are written to the documented output shapes and are the weak spot until T3.8/T3.10 replace them with real captures. On this box the live run exits 1 on `linux.unit.loaded` — correct, T3.9 has not installed the unit. `docs/SERVER-SETUP.md` rewritten: the `## Linux` section now carries the three mandatory fields instead of `WantedBy=default.target`, the title lost "(Windows)", the two `curl` lines became `probe.py`, and a `## Verifying the login scope` section documents the three exit codes. All four acceptance commands exit 0. **Amended by T3.8 (2026-09-19), three defects the Windows box exposed.** (a) `--self-test` was 83/85 *on Windows*: `check_macos_agent` tested `"/Library/LaunchAgents/" in str(path)` and a `WindowsPath` stringifies with backslashes, so the macOS row silently failed on the primary platform — exactly the promise TT.10 rests on. Now normalised. (b) `autologin` shelled out to `reg query` and keyed on the literal `"ERROR:"`; this Windows is pt-BR and prints `ERRO:`, so a value that is simply not set came back UNKNOWN and the whole run exited 2 on a machine with nothing wrong. Replaced with a `winreg` collector — `FileNotFoundError` is a definite "not set", the same in every language — and `_autologin_windows` gained a `MISSING → PASS` branch. The hit is rendered in reg.exe's shape so the committed fixtures stay the contract. (c) `windows.task.enabled` returned UNKNOWN when `Settings/Enabled` was absent, which made every correctly enabled task unverifiable. The Task Scheduler omits that element at its default and writes `<Enabled>false</Enabled>` when a task really is disabled — verified on a live task, disabled and re-enabled, watching the element appear and vanish. Absent is now a PASS. `stop_if_going_on_batteries` was parsed and never asserted, though ADR 0010 lists it among the four; it is asserted now |
| T3.8 | Windows: Scheduled Task, firewall, static IP | blocked | **See `WINDOWS-NEXT-SESSION.md` before touching this** — the panel did not come up by itself on the Windows box on 2026-09-23, reported from the chair, and that file is the triage to run there. 2026-09-19. `server/install_task.ps1` written and run for real on the Windows box; the task is registered, starts `pythonw server.py` windowless, and answers `/ping` on 127.0.0.1:8777. All six shape assertions and `verify_login_scope.py` exit 0 (eleven checks, all PASS). **Blocked on the human half**: the four LAN probes need another device and a reboot/logout, the firewall rule and the network-profile change need elevation, and the DHCP reservation and the BIOS ErP Ready toggle are physical. Three things cost time and are worth not rediscovering. **(1) The interpreter.** `python` on PATH here resolves into an unrelated project's virtualenv, and `py -0p` follows it too because the launcher honours `VIRTUAL_ENV` — its starred default line carries no `-V:` tag, which is how the parser excludes it. A task pointing at a venv works until that project is deleted, then fails at the next login with no console. Resolution is therefore registry-first (`HKLM\SOFTWARE\Python\PythonCore\<tag>\InstallPath`), which is PATH-, venv- and locale-independent; PATH is the last resort, and the script prints which source won. The Store alias is rejected on path and on its zero byte length. **(2) Two acceptance lines were false negatives** — they failed against a *correct* task. `New-ScheduledTaskPrincipal` rejects `InteractiveToken` (its enum says `Interactive`) and `(Get-ScheduledTask ...).Principal.LogonType` reads back `Interactive`, so the cmdlet form could never pass; and `findstr /C:"<LogonTrigger>"` misses a childless `<LogonTrigger />`. The block now reads the exported XML, which is what ADR 0010 and the verifier both name. **(3) The network is classified Public**, so the documented Private-profile rule admits nothing. That would have surfaced as the phone reporting offline forever, indistinguishable from a server bug. The installer reports it and prints `Set-NetConnectionProfile`; it does not widen the rule, because LAN-only is what lets the server have no authentication. Registration goes through the cmdlet objects rather than `Register-ScheduledTask -Xml`: `-Xml` effectively requires `-User`, and `-User` without `-Password` makes the service re-derive the logon type, which is how a task silently lands on S4U. No credential parameter exists in the script at all. `Assert-TaskShape` re-exports and re-asserts after registering, so `PT0S` is an observation and not a belief |
| T3.9 | Linux: systemd user unit (graphical-session) | blocked | 2026-09-21, wave 18. `server/desk-panel.service.in` + `server/install_user_unit.sh`, installed and running on this box: `is-enabled` and `is-active` both answer, `WantedBy` and `PartOf` are both `graphical-session.target`, the unit is **not** in `default.target`'s transitive closure with `Linger=yes` set, no system unit exists, and `verify_login_scope.py` exits 0 on all ten checks — it had exited 1 on `linux.unit.loaded` since T3.5 for want of exactly this file. `probe.py --host 192.168.15.3 --expect up` answers on the LAN address rather than on localhost. **Blocked on the human half**: the SSH round trip needs a second device, and the login/lock/logout sequence needs a graphical logout — the same shape of blocked half T3.8 carries. The installer refuses three installations that would each answer with nobody at the desk (as root, beside a system-scoped unit, or where `graphical-session.target` never activates, which is bare sway/i3 without `uwsm`) and it **detects** the firewall rather than configuring it. Its first cut got that wrong in the dangerous direction: `ufw status` exits 1 as a non-root user, so on this machine — which has ufw installed — it printed *no inbound filter found*, which would send an owner looking everywhere except at the thing blocking the phone. Unreadable is now reported as unreadable |
| T3.10 | macOS: LaunchAgent | blocked | 2026-09-29, wave 34. **The shape half ran on a real Mac** and the behaviour half has not: it needs a logout with a second device to SSH from. `server/dev.bosco.deskpanel.plist.in` + `server/install_agent.sh` are new; the row used to say they shipped, and they did not exist. Shape block exit 0, `verify_login_scope.py` exit 0, `/ping` and `POST /action/*` answer from the agent. The first real run found three defects no fixture could: `--` in the template's XML comment (plutil accepts it, plistlib does not, so the verifier said unknown about a working agent); `parse_launchctl_print` reading the nested `jetsam coalition` block's `type =` and FAILing a loaded agent; and the firewall message naming `python3` when the listener is `Python.app`. Loaded and absent fixtures are real captures now |
| T3.11 | Server portability hardening | done | 2026-09-16. `config_search_paths()` (`--config` → `DESK_PANEL_CONFIG` → `script_dir/config.json`, cwd-independent), `config_permission_warning()` (POSIX-only, warns not refuses), `check_python_version()` (3.11 floor), `Server(HTTPServer)` with `allow_reuse_address = os.name != "nt"`, `--check-only` and `--log-file` flags, explicit UTF-8 everywhere. All 5 acceptance commands exit 0 |
| T3.12 | **Config in TOML, with the catalogue in the file** | done | 2026-09-20. `server/config_format.py` (pure `parse`/`merge`/`format_for_path`, plus `ConfigError`, moved here from `server.py` and re-exported so every existing import still works) and `server/config.example.toml`, which is written as documentation rather than as a sample. **TOML, not the YAML that was asked for**, and the reason is in the file: stdlib-only is a hard constraint in `server/CLAUDE.md`, PyYAML is a dependency, and `tomllib` has been in the standard library since 3.11 — this project's floor. `load_config` dispatches on the suffix; the merge and both parsers are pure, so TT.2 covers every case without a filesystem. **The transition is real and was exercised in all four states** in a scratch rig (neither file, only `.json`, both, only `.toml`): `config.toml` wins, a lone `config.json` still loads and prints one line naming the replacement, and with neither present the not-found message names the `.toml`. **An explicit `--config` or `DESK_PANEL_CONFIG` is never second-guessed** — only the `script_dir` fallback chooses between the two names, because it is the only source that names a file rather than being handed one. Without that rule a launcher pointing at a deleted path would have silently started on whatever config sat in the repo: somebody else's tickers and somebody else's token. `exists` is injected into `config_search_paths`, so it stays pure and the whole matrix is a unit test. **Two things the task file got wrong, both corrected in the catalogue.** (a) "One paid ticker 401s the whole request, so a single unlisted symbol empties the card" is only true when `brapi_symbols_per_request` is raised; at the shipped value of 1 each ticker is its own request and a refused one costs its own row — `load` already works that way. (b) The two upstream catalogues are cited from endpoints that were *checked*, not from a docs page taken on trust: AwesomeAPI lists 540 pairs at `/json/available` and Binance 3,708 symbols at `/api/v3/ticker/price`, and every pair and coin named in the example was confirmed present. **`config.example.json` shipped `quotes_interval_s: 300` while the default was 600** — the arithmetic beside `DEFAULT_CONFIG` says 300 burns brapi's 15,000/month budget by the 17th, and copying that file was the documented first step. Fixed, the three keys it was missing added, and a test now asserts the example's key set equals `DEFAULT_CONFIG`'s in both directions and that neither example ships an interval below the default. The `theme` key is reserved and defaulted to `neon` for T6.7. `config.toml` inherits the gitignore rule and both agent denylists (`.claude/settings.json` and `reasonix.toml`, changed together). **`install_task.ps1` learned both formats and that half is unverified**: no PowerShell exists on this box, so `Resolve-DeskPanelConfig` and the TOML branch of `Get-ConfiguredPort` were reviewed, not run. The port scan is a line scan that stops at the first `[section]` and warns when it finds nothing, so a miss degrades to the 8777-plus-warning the function always had. All four acceptance commands exit 0 (re-run after the review's fixes); `make lint-tasks`, the web suite and the Android JVM suite are green. **Four review findings, all four applied before the merge** — see the wave 12 section below; the worst was the migration notice giving a launcher-started server advice that would have silently done nothing |
| T3.6 | Serve the APK at `/app` | done | 2026-09-23, wave 22. All five acceptance lines exit 0, and they exit 0 on a checkout with no `out/` at all — **which the first version did not**: the review found both probes assert 200 on a route that correctly answers 404 after `make clean`, on a fresh clone and in the CI that TT.9 is about to add, so the criterion was one about this desk. It brings its own four-byte fixture now, and deletes it, because an APK left in `out/` is a file `/app` hands to a phone. `/app` serves **`desk-panel-release.apk` when it is there**, newest-by-mtime only among the rest — the review's other real one: `make apk` is `assembleDebug` and drops `app-debug.apk` into the same `out/`, so newest-by-mtime routinely picks the debug build, which cannot install over the release-signed one the panel runs. `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, and the only way past it is an uninstall, which drops the MIUI toggles a person has to re-grant standing at the phone. The index page says so when what it offers is not the release build. A missing `out/` is 404 and not an error: a fresh clone has none, and that is "build first", which the body says in plain text because the client here is a person holding a phone while every other error in the file is JSON for the panel. `/` is one page with one link, so the phone remembers a host and a port instead of a path. **The route's shape forced two changes with more reach than the route.** `route()` now returns four values, not three — extra headers are the router's, not the handler's, and `Content-Disposition` is what stops the browser saving the download as `app` with no extension; nine unpackings in two test files moved with it. And `HEAD` did not exist: `do_HEAD` routes as GET and drops the body, so Content-Length still describes the body a GET would return, which is the only thing that makes the acceptance worth writing as HEAD. **`--expect-header` had to be built before the acceptance could run** — `probe.py` discarded headers entirely, and the criterion it replaces, `curl -sI | grep -i content-type`, passed whenever any content-type came back. Proved it can fail, four ways, including that a prefix does **not** match: `application/vnd.android.package` is rejected against `application/vnd.android.package-archive`. 216 server tests, up from 195 |
| T3.7 | `POST /action/{id}` stub returning 501 | done | 2026-09-19. Rode along with wave 8 because TT.3 was `blocked` on it as well as on T3.3, and stranding TT.3 a second time for a five-line route would have been the more expensive choice. Matched narrowly by a pure `action_id(path)`: one segment, non-empty, no nesting, no `..`, no query — which is the first half of the closed-allowlist promise in `server/CLAUDE.md`. 501 rather than 404 or 200, because the route exists and does nothing yet, and that is exactly what 501 says. `probe.py --serve --url /action/anything --method POST --expect-status 501` exits 0 |
| T3.13 | **One command to run after a pull** | done | 2026-09-22, wave 20. `scripts/after_update.py` + `docs/UPDATING.md`. Written after an evening lost to a server that was **one minute older than the code it was serving**: the Scheduled Task had started at 00:31:18, the pull rewrote `server.py` at 00:32, and the phone's two new cards (T6.13, T6.15) were empty while every check this repo owns said the machine was healthy - `/ping` answered, the config was valid, the APK was current, `probe.py` would have exited 0. **A pull is not a deploy**, and "does it answer" cannot tell yesterday's server from today's. So the script's load-bearing step compares `/weather` against the key set the tree's own `normalise()` produces, imported rather than hardcoded, plus `moon` when `providers_usno.py` is present - a field added to the payload later starts being required with nobody editing the script. It **asks the launcher** on every OS and never spawns the server (invariant 2; the acceptance greps for `Popen` to keep it that way), takes every path out of the launcher's own action rather than the repo, and **waits for the socket between stop and start** - discovered the hard way, a back-to-back `Stop`/`Start` hit `WinError 10048` and took down the survivor too, because `allow_reuse_address` is off on Windows on purpose. **The test suite deliberately does not gate the restart** and the first cut had that backwards: the new code is already on disk and the next login loads it regardless, so refusing would leave the panel stale *and* the tree broken. A broken config does gate it. macOS reports `unknown` rather than guessing (T3.10 is `blocked`), and `docs/UPDATING.md` records the three things that join the script when a Mac exists. `--self-test` covers the pure functions on any box, 35 cases, and caught `python_for` corrupting `/usr/bin/python3` into `\usr\bin\python3` by round-tripping through `Path`. **Six review findings, all six real and all six applied.** The one that mattered: **the Linux branch was unreachable code** - `config_path` was assigned only inside the `win32` branch, so Linux reached a launcher and never a port, and `restart_linux`, `step_payload` and `step_login_scope` could not run while this task file and `docs/UPDATING.md` both described them running. `parse_exec_start` now reads the unit's quoted `ExecStart` from the **file**, not `systemctl show -p ExecStart`, whose `argv[]=` resolves the quoting and makes a path with a space look like two arguments. Then: a **cold weather cache was announced as stale code** (the payload check runs when the cache is empty by construction, and a failed first fetch drops to a five-key fallback - it now reads the `stale` flag the payload already carries); an **`apk` failure pinned its own marker**, since FAIL means exit 1 and exit 1 is what stops the marker advancing, so no rebuild could clear it - `--rebuilt` is the explicit acknowledgement, explicit because the repo cannot see the phone; a **refused `Stop` was blamed on "something else owns it"** with the real error discarded; **`--dry-run` printed "all clear" and exited 0** on the exact machine state the script was written for, the deciding check being the one a dry run cannot make; and a red web suite reported `FAIL` with no detail. The Linux path was then **simulated** - platform patched, fake unit, end steps stubbed - which proves it is reached and proves nothing about `systemctl --user restart`, still never executed. **The macOS branch exists since wave 34** and ran on a Mac: paths from the agent's `ProgramArguments`, restart through `launchctl kickstart -k`, every step `ok` but the first-run `apk` |
| TT.2 | Server unit tests + fixtures | done | 2026-09-19. Re-opened by wave 8, as its earlier note asked. 86 tests now, up from 32: every provider normaliser against a **real recorded response** in `server/tests/fixtures/`, plus the cache, the stale fallback and the payload assembly. The fixtures are captures, not hand-written shapes — which is the point, since the shapes for crypto and FX were not in anybody's documentation. `TimedCache` takes `now` as an argument and `App` takes its clock, so a 300s TTL expires in a function call rather than a sleep. **A test found a real defect**: after a failed refresh the cache did not move `fetched_at`, so every subsequent request retried — an upstream that is down would have become one outbound call per panel poll, the exact traffic the cache exists to prevent, arriving when the upstream can least afford it. A failure now spends the TTL like a success does. The acceptance's real check passes too: the whole suite is green inside a network namespace with no route out, proved by a `URLError` on a live URL from that same namespace |
| TT.3 | Two HTTP integration tests on port 0 | done | 2026-09-19. Steps 5 and 6 landed, which is what it was `blocked` on: `/quotes` over a real socket asserting the T1.2 contract shape key by key, and `POST /action/x` returning 501 with `GET` to the same path still 404. Still no network — the provider modules' `load` is replaced, so the payload comes from the test file and `upstream.py` is never reached. A second server on its own port 0, built with `functools.partial(Handler, app=...)` rather than a class attribute, because a class attribute would be shared by every server in a process that starts more than one. Content-Length is asserted against the **byte** length on a payload carrying `São Paulo`, since a length computed on characters truncates the body and the client hangs |
| TT.4 | Contract tests, opt-in | done | 2026-09-24, wave 23. **Five upstreams, not the two the task file listed** — crypto and FX moved to Binance and AwesomeAPI when brapi turned out to charge for them (T3.3 subtask 0), and the moon arrived with T6.13; an upstream this file does not cover is one whose schema change reaches the desk as a blank card. 15 live cases, all green against the real APIs. Shape, never value: a helper asserts a field is **parseable as a number** rather than typed, because brapi sends JSON numbers where Binance and AwesomeAPI send the same quantities as strings and every normaliser runs `float()` anyway. Three cases are about more than presence — Binance's kline close is **positional** at index 4 and an inserted column would silently redraw the sparkline from the volume; open-meteo's daily arrays are asserted to still align with `current.time`, because the timezone parameter failing reaches the panel as a missing min and max rather than an error; and the USNO window is asserted to still bracket now with two New Moons, which the first cut of `LOOKBACK_DAYS`/`NUMP` did not. **The assertion mechanism got its own tests first** (wave 22's rule): 21 offline cases prove every helper fails and names the path, including the ones that would otherwise pass — `float(True)` is 1.0, so a price that became a flag reads as one; an empty `results` array must fail with a message rather than raise IndexError naming no field. `LIVE` sets a `needs_network` tag of its own **because `skipUnless` is the identity function once the variable is set** and leaves nothing to walk the module for — a case added without the decorator would then be invisible to everything but review, and it would be the one case that opens a socket from `make check`. 244 server tests, up from 223 |
| TT.10 | Login-scope verifier tests, from fixtures | done | 2026-09-21. Makes T3.10 checkable without a Mac. 97 recorded cases now run under `unittest discover` as well as under `--self-test`, imported rather than copied; purity is asserted by nailing `run_command`, `read_registry_autologin`, `read_file` and `file_present` shut and re-running them all. Two rows of the task's fixture table were amended: the verifier proves the unit is outside `default.target`'s closure rather than checking `Linger`, which is the stronger property and is why T3.9 may pass with `Linger=yes`; and WSL is read from `/proc/sys/kernel/osrelease`, not `/proc/version`. Writing the named cases found that `detect_autologin` dispatches on `"win32"`, so a test spelling it `"windows"` silently tests the Linux branch |
| TT.11 | The unit-rendering test skips a shell that cannot run it | done | 2026-09-22, wave 20. **Found by T3.13** on a clean `main`: the server suite was red on the Windows host with eight failures, and had been since wave 18 landed. Not the escaping, which is what it looks like and what the file's own docstring says has been wrong twice - read out of `install_user_unit.sh` and run through `sed -f`, the shipped `s/[\\&|]/\\&/g` is provably correct. **It is the transport**: Git Bash hands the `-e` argument to a native `sed.exe` through MSYS2's conversion, one backslash is eaten, and the escaping silently returns every path unchanged. Three reproductions were wrong before that landed, each mangled by a different quoting layer - including the agent's own shell collapsing `\\` in the diagnostic commands; only reading the bytes out of the file settled it. `shell_passes_backslash_to_sed()` hands sed a fixed `s/x/\\y/` and requires `\y` back, and **deliberately never calls `sed_escape`** - a skip keyed on "the escaping looks wrong" would have gone green for both historical bugs, so the acceptance asserts the probe does not call the function under test. Detected, never assumed from `sys.platform`, which would guess at which shells mangle arguments and lie the day MSYS2 fixes it. The suite is 191 tests, green, one skip; the escaping stays verified on Linux, where the installer actually runs |
| TT.12 | The self-tests nothing runs | done | 2026-09-24, wave 24. Both scripts are green and `make check` now reaches them. `python_for` took the flavour from the OS instead of from the string, so on Linux `Path(r"C:\Py\pythonw.exe").name` was the whole string and the swap silently did not happen; a `_pure()` helper picks `PureWindowsPath` or `PurePosixPath` from the path itself, which is the mirror of the defect T3.8 fixed in `verify_login_scope.py`. `check_status.py` read every comma-separated prereq as a task id, so `ADR 0015` became `prereq ADR does not exist`; **the ADR is deliberately not required to exist** — T9.1 and T9.2 are blocked on it being written, and a prerequisite you have not met yet is the normal case. The shape is checked, so `ADR fifteen` still fails, and the number cannot be. Two new targets: `lint-status` and `lint-selftests`, the latter discovering by `grep -l -- '--self-test' scripts/*.py` rather than by a list, so the next script to grow one is covered by being written. Both mutation-tested: a hardcoded-list recipe fails the fourth acceptance line, and a malformed ADR plus a missing task prereq both still exit 1. **The Linux half is unproven on this desk** — no WSL, no Docker, so the fix is verified by construction (no `Path` remains in the decision) and by the two cases passing on Windows, not by a green run on Linux. CI is where that lands |

## Phase 4 — The core behaviour

| # | Task | State | Notes |
|---|---|---|---|
| T4.1 | `network_security_config.xml` | done | 2026-09-16. `res/xml/network_security_config.xml` grants cleartext to one `<domain-config>` and nothing else; no `base-config`, no `android:usesCleartextTraffic`. `includeSubdomains="false"` because a bare IP has no subdomains and the default would widen the exemption. Manifest gains `INTERNET` and `android:networkSecurityConfig` on `<application>`. Address is the agreed placeholder `192.168.1.100` — the DHCP reservation belongs to T3.8, which is `blocked` on the Windows PC, and T7.3's acceptance requires exactly this literal in committed non-doc source, so the placeholder is the correct committed value either way; a comment in the file says what to change. All five acceptance commands exit 0. Verified past the greps: `aapt2` on `out/app-debug.apk` shows the manifest attribute resolving to `@0x7f010000` = `xml/network_security_config`, and the packaged binary XML decodes to the single pinned domain |
| T4.2 | `PcPoller` | done | 2026-09-16. All five criteria green on the real phone (Redmi Note 10, `303f1f9c`) against the dev box serving as the PC. `PcPoller` is the app's only network code and the thin shell it was specified to be: it owns the socket and the scheduling, `PcState` owns every decision, and it starts in `onResume`/stops in `onPause` while being constructed once in `onCreate`, so a pause/resume pair is not a state reset and cannot re-log a transition that never happened. 1500 ms on both timeouts, deliberately under `ONLINE_INTERVAL_MS`, so a dead PC cannot look alive for most of a minute; the failure path has to be as prompt as the success path because switching the screen off is the product. Measured: `state=online` 19:40:48, server killed and `state=offline` 19:41:13 with `probe failed: java.net.ConnectException`, recovery `state=online` 19:41:42, and **0** `state=` lines in 30 s of steady state against a `-le 1` budget. **Two acceptance criteria were wrong and are rewritten**; the task file carries both. (1) The online block cleared the buffer and slept, which observes a transition only by luck — in steady state nothing logs, by design. It is now `force-stop`, clear, `am start`, sleep, grep, the same ordering the backlog-run note argues for and for the same reason. (2) The cleartext grep was **unachievable from the shipping APK**, not merely unmet: `build.gradle.kts` substitutes one placeholder across the whole generated `res/` tree, so `pc_host` and the pinned domain are the same address by construction and the app never dials anything the pin forbids. Proved instead with a throwaway divergence build — `pc_host` set to a literal `192.168.15.4` the substitution does not touch, pin still at `192.168.15.3`, the build printing both — which yields `java.io.IOException: Cleartext HTTP traffic to 192.168.15.4 not permitted`. It surfaces through `PcPoller`'s per-transition reason line, exactly as that method's comment predicted: the platform raises it, and an exception nobody prints is a silent offline. Reverted and the revert proved, not assumed — placeholder back, rebuilt, reinstalled, `state=online`, zero cleartext lines. **Two environment facts that cost this run a session.** The Linux box acting as the PC runs **ufw**, and `docs/SERVER-SETUP.md` explicitly ships no firewall step for Linux; the phone is on `192.168.3.100/24` while the PC is on `192.168.15.3/24`, so the rule has to cover both and any NAT between them: `sudo ufw allow from 192.168.0.0/16 to any port 8777 proto tcp`. Until it was applied the phone pinged fine and the HTTP probe timed out — DROP, not refused, which is what the app reports as a plain offline. And **an adb install needs a human at the phone**. MIUI raises a confirmation dialog on the device for the first install of a session; unanswered, it returns `INSTALL_FAILED_USER_RESTRICTED: Install canceled by user` in about four seconds — fast enough to read as a hard policy refusal, which is what it was mistaken for here. Three attempts failed while nobody was looking at the phone, and the next one succeeded the moment the owner tapped *authorise* on the screen that had been sitting there. Later installs in the same session went through with no prompt. The mistaken reading recorded first was that MIUI refuses debug-signed APKs and accepts release-signed ones — the debug attempts simply happened to be the unattended ones, and were never retried after the authorisation, so nothing here says anything about signing at all. T2.2 hit the same error and cleared it by cycling Developer options → "Install via USB", so that toggle is the second thing to check when the dialog never appears. Independent of all of it: an on-device experiment has to go through `assembleRelease`, which overwrites `out/desk-panel-release.apk` — back it up first |
| T4.3 | Wire to `onPcState()` + brightness | done | 2026-09-19. 🏁 **Milestone B reached.** Both acceptance commands exit 0 on the device, and the PC going away now takes the screen with it. **Step 3 (brightness) was deliberately not implemented** — T4.4 landed in the same wave, so writing the dim-to-black path first would have meant writing code whose only purpose was to be deleted an hour later; `screenBrightness` stays at the window default `-1f` and the task file records the divergence. The real work was the question T4.2 opened and this task had to answer: **who owns the poll loop once the Activity is not resumed.** Answer, in [ADR 0014](../docs/adr/0014-poll-loop-outlives-the-screen.md): a started foreground service, `PanelService`, holding a `PARTIAL_WAKE_LOCK` for exactly the offline stretch, and raising the Activity with `REORDER_TO_FRONT` when the PC returns. The wake lock is affordable only because the board keeps USB powered with the PC off, so offline means *charging* with the screen off — that assumption is written into the ADR along with the power-aware branch to build if ErP Ready is ever disabled. Ownership is now one concern each: `PcState` decides meaning, `PcPoller` owns the socket and schedule, `PanelService` stays awake and logs `state=`, `MainActivity` owns the window and logs `screen=`. `PcPoller` lost its `Log` and took a `Listener`; `MainActivity` lost `onResume`/`onPause` entirely. One bug fixed before it could happen: unregistering the panel is compare-and-clear, not a null assignment, because the wake relaunches the Activity and a blind clear would unregister the live instance on behalf of the dead one — silent and total, since the markers keep coming from the service while the page is never told anything again. `web/js/app.js` toggles `body.pc-offline` (children hidden over a `#000000` ground) and stops the 1Hz clock interval while offline. **Reviewed before merge, eight findings, all applied.** Three were real: a `START_STICKY` restart came back with no Activity registered, so the next wake logged nothing and turned nothing on — defeating the very restart the ADR asks for; a relaunched Activity held `FLAG_KEEP_SCREEN_ON` through an offline night because nothing ever told it the state, since only edges are delivered; and `setTurnScreenOn`/`setShowWhenLocked` were latched on rather than paired with the state, so any later resume with the PC off would wake the screen over the keyguard. All three are one omission — nothing replayed the current state to a window that arrived late — and the fix is a replay in `PanelService`, which does not log a marker except when the transition happened with no window to log it. The rest: `NEW_TASK` on the notification's `PendingIntent`, `stopIfUnclaimed` so the departing Activity cannot stop the service its replacement just started, the offline wake lock released on window focus rather than at `startActivity` (which only queues the request and returns), the page re-told its state on `onPageFinished` since a state delivered before `app.js` parses is a silent `ReferenceError` that only edges would never repeat, and an over-promising `POST_NOTIFICATIONS` comment corrected. The keep-screen-on fix was verified on the device and the probe proved to discriminate: the flag is found while online and absent after a forced relaunch while offline |
| T4.4 | Real screen sleep, replacing brightness zero | done | 2026-09-19. **ADR 0005 keeps its primary design — MIUI honours `setTurnScreenOn`.** Four consecutive cycles took the display from `mWakefulness=Dozing` to `Awake` with nobody touching the phone; both acceptance commands exit 0 at their 30s windows and the tighter 20s ones too. The decision is written into ADR 0005 as the task required. **Two device settings decide it, and the app cannot reach either.** First, MIUI denies *Show on Lock screen* by default: with it denied the Activity is raised, `state=online` and `screen=wake` are both logged, and the screen stays dark — the only evidence anywhere is one `MIUILOG- Show when locked PermissionDenied` line. Second, Developer options → *Stay awake* was on, which pins the screen lit for as long as the phone is charging, i.e. always on this desk; `INSTALL-PHONE.md` had been **recommending it**, left over from the abandoned brightness design, and that step is now inverted. Both are app-ops or settings that `adb install -r` resets, which is documented with the numeric ops (10020, 10008) read off the device. The device PIN turned out not to matter — the keyguard was up in every successful cycle. Not done: the eyes-only half. `Dozing` is adb's word, not a human's, so *actually dark in a dark room* and *comes back without touching the phone* are **both confirmed** (2026-09-19, at the device). The eyes earned their keep: the panel came back **upside down**, `ROTATION_90` where this stand wants `ROTATION_270`. `sensorLandscape` re-decides the direction on every Activity creation, which never mattered until this task made the wake relaunch it, with the phone lying nearly flat in a stand where the accelerometer is ambiguous. Fixed in the same wave by making the direction build-time config — `PANEL_ORIENTATION` in `.env`, validated against the three legal values and defaulting to `sensorLandscape`, which is a new instance of the ADR 0013 rule and is recorded there. Re-verified: rotation unchanged across a full sleep/wake cycle |
| T4.5 | **The panel follows more than one PC** | blocked | 2026-09-29, wave 35. ADR 0016. `PC_IP` is a list; the pin gets one `<domain>` per host; `PcHosts` (12 JVM tests) asks the last host that answered first and stops at the first 200; data and presses follow it. Built with two addresses and the generated pin inspected: two `<domain>`s, no `base-config`; a bad octet fails the build by name. **Half of it ran on the phone, 2026-09-29**: release build with both addresses installed over the old one (same key, settings kept); with the Windows PC off it logged `pc answered at <mac>`, `state=online`, `screen=wake`, `data=ok` within 20 s. Still blocked on the other half: the move *between* two live PCs, which needs the Windows PC on and a logout |
| T4.6 | **The panel sleeps with the PC's display** | done | 2026-09-30, wave 39. Asked for the same day. [ADR 0020](../docs/adr/0020-the-panel-sleeps-with-the-display.md): `/ping` carries `display: on/off/unknown` and the phone sleeps on "off" — the PC decides when its monitor sleeps, so following it is invariant 3 applied, not a timeout. **"unknown" is the landing place for every failure**, and only the literal "off" darkens the panel. `PcState.IDLE` takes the offline path for the screen but keeps the 2 s cadence, and is dormant on battery. With two PCs a dark one does not end the cycle. **Measured:** macOS's reader on the owner's Mac, and the phone half on the Redmi (`state=idle` → `screen=sleep`, back on the next poll). **Not measured:** the Windows and GNOME readers, which are written from the vendors' docs and unit-tested on their decoding |
| TT.5 | `PcState` extracted + JVM tests | done | 2026-09-16. `PcState.java` is plain Java — no Android imports, no clock read internally, no threads, no sleeps: every time-aware method takes `nowMs` as an argument, so T4.2 can drive it unmodified. It owns the state (`UNKNOWN`/`ONLINE`/`OFFLINE`, starting `UNKNOWN` so the first probe either way is a transition), the consecutive-failure count, `nextIntervalMs()` (2000 online; 2000/4000/8000 doubling, capped at 15000 offline, reset on first success), and `nextProbeAtMs()`/`isDue()` so `PcPoller` can keep no deadline of its own. It decides *that* a transition happened and returns it; emitting `state=online`/`state=offline` stays on the Android side (TT.6). 16 JUnit tests; both acceptance commands exit 0 and `./gradlew test` finishes in seconds. The suite was checked against 10 mutations of `PcState` — flapping, deaf, stuck, uncapped backoff, no reset, flat backoff, backoff one rung too fast, `isDue` off by one, deadline ignoring the backoff, failures uncounted — and every one turned it red |
| TT.6 | Logcat markers | done | 2026-09-19. `Markers.java` holds the vocabulary — `state=`, `screen=`, `night=`, `tick=`, `ping=`, `data=`, `battery=` and the `DeskPanel` tag — and the grep that no marker string exists anywhere else under `main/java` exits 0. **It builds the strings and does not log them**, against the task file's step 2, because `android/CLAUDE.md` says anything worth testing lives in a class with no Android imports: a contract the E2E suite greps for is exactly that, and `MarkersTest` now asserts all eleven literally on the JVM, which a class holding `Log.i` could not offer. The property the acceptance enforces — one place per string — holds either way, and the two call sites that own a transition do the logging. Only `state=` and `screen=` have emitters today; the rest are the contract their own tasks will wire. **The acceptance's own ordering was wrong and is fixed**: it said kill the server, then `adb logcat -c`, and the app notices within one 2s poll, so the clear usually lands after the transition and wipes the marker being asserted on. It failed exactly that way here, with an empty log and an app that had done everything right — the same trap `am start` cost a session over. All three task files and `docs/TESTING.md` now clear the buffer before touching the PC |

## Phase 5 — Real data

| # | Task | State | Notes |
|---|---|---|---|
| T5.1 | `DataPoller`, replacing the mock | done | 2026-09-19. Real quotes, FX, crypto and weather on the panel; all three acceptance commands exit 0 and the manual check was done against a screencap, value by value. `DataPoller` is a sibling of `PcPoller`, deliberately not merged with it: they answer different questions on different clocks, a 2s heartbeat that decides whether the screen is on at all against a 60s refresh of what it shows. It runs **only while online** — offline the panel is dark and the device is up on a wake lock held to notice a login, and spending that on numbers nobody can see is the opposite of ADR 0008. The interval is not config: the server decides how often to hit an upstream, the phone only decides how often to ask a server that is already caching, so a value here cannot burn anybody's API budget. `DataPayload` is the part worth testing and has no Android imports, so the merge is covered on the JVM — `org.json` is bundled with Android but its JVM stub throws, so the real artefact is on the **test** classpath only. **Merging is all-or-nothing**, and that is a choice about wiping: `onData` is a full replacement and `app.js` clears each section before rendering it, so half a payload erases the half that failed, which is worse than sending nothing when the panel already holds values a minute old. A hostile ticker is a test, not a hope: a symbol that closes its own literal and appends a call survives as data, because the payload is built through `org.json` rather than concatenated. U+2028/U+2029 are escaped too — legal unescaped in JSON, line terminators in pre-ES2019 JavaScript, and silent. `web/js/app.js` needed **no changes**, which is what the contract was for |
| T5.2 | Timeouts, retry, failure tolerance | done | 2026-09-19. All four assertions exit 0 against a real 30s Wi-Fi outage. Most of what this task asks for was already standing — 1500ms timeouts on `PcPoller`, a catch-all around every probe, an all-or-nothing merge that keeps the last values rather than blanking a card, a failure counter that a single success resets — because T4.2 and T5.1 had to build it to work at all. **The one real gap was the reschedule.** Both pollers booked the next cycle at the end of the runnable, so any exception raised after the probe returned would end the chain for the life of the process: a `ScheduledExecutorService` parks a runnable's exception in a `Future` nobody reads, and the panel would have gone on showing the last payload with nothing anywhere saying the loop was gone — this task's own "worst failure mode available". The reschedule now lives in a `finally` in both pollers, with the body split out so no path can step over it, and a `Throwable` catch above it exists only to make the reason visible. **The acceptance itself was wrong and is fixed**, the same way TT.6's was: it cleared the log *after* the outage, throwing away the part of the log the test is about, and then asserted `grep -q 'state='` to prove the poller was alive. `state=` is a transition marker, so a healthy panel that has been online for a minute logs none — the assertion measured whether a transition happened to fall inside the window, not whether anything was running, and it fails on a perfectly healthy device. Proved here: run verbatim, it reported `note: no state= in a steady-state window`. The clear now goes before the Wi-Fi is dropped and liveness is asserted on `ping=ok`, the heartbeat T5.3 adds. Measured on the device: the panel noticed the network go, backed off 2/4/8/15/15, came back 13s after Wi-Fi returned, restarted the data poller in the same second, and no crash, ANR or exception trace appears anywhere in 3340 lines of log |
| T5.3 | Adaptive polling with backoff | done | 2026-09-19. Requirement, not polish — ADR 0008. Three of the five steps were already in `PcState` (the 2/4/8…15s ladder as a pure function of consecutive failures, the reset on first success) and in `PanelService` (the data poller stopped on the way down, started on the way up), all covered by the JVM tests T4.2 shipped. **What was missing was the evidence.** `Markers.ping` had been defined by TT.6 and was emitted by nothing, so the acceptance's `grep -c 'ping='` counted zero and passed `-le 4` while proving exactly nothing about the cadence. `PcPoller` now logs it once per probe, after the staleness check so a straggler from a replaced generation cannot inflate the count with polls that are no longer anybody's cadence. Measured with the server stopped: **4 pings and 0 data requests in the minute**, and `state=online` 11s after the server came back. **The `-le 4` only holds in a steady-state minute** — 4 is `60 / BACKOFF_CAP_MS`, and a minute measured from the moment the PC goes away legitimately holds seven, because it contains the 2, 4 and 8 second rungs too. The task file now says to give the panel twenty seconds before clearing the log, and fixes the recovery check's ordering to clear before starting the server rather than after |
| T5.4 | Battery telemetry | done | 2026-09-19. The DEVICE card is no longer empty, and is no longer a card. Both acceptance commands exit 0; on the device the corner reads `BAT 22% · 25.2°C`, which matches `dumpsys battery` (level 22, scale 100, temperature 252) exactly. **The receiver lives in `PanelService`, not `MainActivity` as the task header said** — the Activity is stopped for the whole offline stretch, so an Activity-scoped receiver would be gone precisely while the phone is running warm on a wake lock in a dark room, which is the case a thermometer is for. `BatteryReading` is plain Java and carries everything that can be wrong about the numbers: the level is read against its own `EXTRA_SCALE` (a device reporting out of 255 would render a full battery as 34%), clamped rather than trusted, and the temperature keeps the tenth the extra actually carries. **`ABSENT` is `Integer.MIN_VALUE` and not -1**, because -1 tenths is -0.1 degrees — a real if unlikely reading, so the obvious sentinel would have made a missing extra indistinguishable from a cold morning. `DataPayload.withBattery` folds it in as a second step rather than a third argument to `merge`, because the two halves do not share a clock, and its failure rule is the **opposite** of `merge`'s on purpose: a battery that will not parse returns the payload untouched, since blanking B3, FX, CRYPTO and WEATHER over a temperature is not a trade anybody would make. **The broadcast is not a render.** It fires roughly every eight seconds while charging, on voltage movements that change nothing visible at one decimal place, and `onData` is a full rebuild of every card — so `publish()` compares the folded payload against what the page already has and stays quiet when they match; the `battery=` marker still fires per broadcast, because a receiver that silently never fires is the failure this task names. The demotion the task asked for is done and measured: `#battery` leaves the grid for the panel's bottom-right corner, WEATHER spans all three rows, and `check_layout.py` passes both payloads at 872x392 with WEATHER at 224x372. Inset by 1px, not 0 — at 0 the line's black ground painted over the card's border and left it looking broken open. Above 40 degrees the line takes a new `--warn` amber (11.7:1 on black): a colour, not a badge, because a warm battery on a charger is worth noticing on the way past and is not a fault. **Reviewed before merge, four findings, all applied, and two were real bugs this desk would have hit.** The corner line was `nowrap` and positioned against `#panel` rather than the 224px track it appears to live in, so its widest variant — `BAT 100% · 42.5°C · unplugged`, 323px — grew out of the column and painted its opaque black ground over the bottom of the CRYPTO card, hiding a live price's change and its sparkline over 68x15px. It is now `box-sizing: border-box` with a 222px cap and allowed to wrap, and `#weather` **reserves** the foot it sits in with `padding-bottom` instead of sharing it — verified with a city more than twice the stress fixture's length. And `isCharging` read `EXTRA_STATUS`, which reports `BATTERY_STATUS_NOT_CHARGING` whenever a charge is paused with power still connected — MIUI's own optimisation, a thermal limit, 100% on a charger — so the panel would have said "unplugged" with the cable plainly in. It reads `EXTRA_PLUGGED` now. That word is not decoration: this file uses it as the evidence for whether ADR 0014's wake lock is still affordable, so a false one argues for rewriting the poll loop to solve a problem that does not exist |
| T5.6 | **Power-aware offline polling: the ADR 0014 branch** | done | 2026-09-19. Asked for ahead of T5.5. ADR 0014 holds a `PARTIAL_WAKE_LOCK` for the whole offline stretch and says it is affordable only because the board keeps USB powered with the PC off. **Measured, and the assumption is false — but not for the reason the ADR predicted.** ErP Ready was never the problem: USB is live with the PC on. The port negotiates `Max charging current: 100000` — **100 mA** — and the phone lost 22% to 20% in 27 minutes *while reporting `status: 2`, charging*, about 4.4% an hour. The supply is simply smaller than the draw. So the offline stretch is the one place the arithmetic can still be won: screen off, a partial wake lock is roughly break-even against 100 mA, and dropping it turns those hours net-positive. The ADR's other claim was wrong too, and it was the weaker one — "it cannot be tested on this desk today". `adb shell dumpsys battery unplug` overrides what the framework reports and fires the real `ACTION_POWER_DISCONNECTED`, which is the layer the app reads; the whole branch is exercised in two minutes without touching the cable or the BIOS. **Untestability is worth checking before it is used as a reason not to write something.** Dormant is one state and one only — offline *and* on battery — and the difference from the ADR 0014 arrangement is not a cadence but an owner: nothing in the process may hold the CPU, so there is no thread to run a ladder on and `AlarmManager` keeps the time. `PcState.isDormant` is pure and has five JVM tests; 50 now, up from 43. Measured on the device: `dormant=on`, then **90 seconds of complete silence** where the old code managed six probes, and `DeskPanel:offline-poll` gone from the held-lock list. Power back: `dormant=off` and a probe **36ms** later. **Two assertions had the same history trap**, found before either was trusted: `dumpsys power` and `dumpsys alarm` both print a history beside the live state, so a bare grep for the tag matches a lock released or an alarm cancelled hours ago — the naive grep finds three lines whether the alarm is armed or not. Both are scoped now, and both were proved to discriminate in each direction. **A third assertion could not have passed at all** and was rewritten: waiting 60s for recovery with no power event, against a 15-minute alarm. What is assertable in seconds is that the alarm is armed, of the right type, and cancelled when it should be; that it *delivers* is the long check. **Reviewed before merge, six findings, all applied, and two were bugs that would have stranded the panel.** Plugging in fires `ACTION_BATTERY_CHANGED` as well as `ACTION_POWER_CONNECTED`, and the two receivers raced: whichever landed first cleared the dormant flag, so if the battery broadcast won, the power receiver saw “not dormant”, skipped the probe, and the alarm had already been cancelled — nothing would ever have polled again, and the panel would sit dark with the PC on until the service restarted. The device happened to deliver the harmless order, which is why the acceptance passed; ending dormancy and probing are one step now. The second: mains returning while *still offline* restored the in-process ladder but took no wake lock, because the acquire hung off a `state=` transition that does not happen — the executor would have stopped firing at the next suspend with the alarm already cancelled. Also fixed: `probeNow` takes a new generation, since two triggers arriving together would have forked the poll chain permanently — the double-rate overnight failure `generation` exists to prevent and the one case it could not catch; the `dormant` static is reset on service create, or a stale true would swallow the `dormant=on` the acceptance greps for; and the probe's wake lock is released when the probe is accounted for rather than held for its full 10s window ninety-odd times a night, on the one path whose purpose is not to hold the CPU. **The sixth finding is not code**: dormancy means `EXTRA_PLUGGED == 0`, and this desk drains *while plugged*, so the overnight win is conditional on USB dying with the PC — untested here, because the dev box is the PC. **And the review's long check found a seventh thing, bigger than any of them.** The 15-minute alarm was being deferred to **three days**: requested `+12m51s`, scheduled `+3d0h12m51s`, and *listed as armed* the whole time — so the acceptance's “the alarm exists” check passed while recovery was three days away. The cause is Android's battery optimisation, which the app was not exempt from: `INSTALL-PHONE.md` step 2 is **MIUI's** list and Android's is a different one, and only Android's governs alarms. `dumpsys deviceidle whitelist +dev.bosco.deskpanel` removes the deferral outright — `power_pending` goes from `+3d0h12m51s` to `--` and the alarm lands at `+14m41s`. That is now step 6 of `INSTALL-PHONE.md` with its own command, and the acceptance asserts both the whitelist and `power_pending=--` rather than the alarm's mere presence. It was found because the long check came back **empty after seventeen minutes**, which was itself finding 2 reproducing in the wild: mains had returned while offline, the ladder was restored with no wake lock, the device suspended, and the loop was simply gone — no alarm, no markers, nothing. **One thing ships unverified, and it is named rather than glossed:** the alarm has never been observed to *deliver*. The second attempt, on the fixed build with the whitelist, also came back empty at eighteen minutes — but this time the alarm was still legitimately pending, because `setAndAllowWhileIdle` is inexact and the platform had scheduled it `whenElapsed=+14m41s` against `maxWhenElapsed=+25m56s`. The wait was inside the window. So **the worst case is about half an hour, not the fifteen minutes the constant asks for**, and every file that said fifteen now says so: `PcState`, ADR 0014, `TESTING.md` and the task's own steps. The manual check is rewritten to wait thirty-five minutes and to read `maxWhenElapsed` rather than trust the constant. Everything else in the task is green on the device; this one path is the mechanism of last resort and it is still owed a measurement |
| T5.5 | Thermal screen cutoff | done | 2026-09-20. Invariant 3 now has two authorities, and all four device assertions exit 0: `screen=thermal` at 46 °C injected, `screen=thermal-clear` at 30 °C, `mWakefulness=Awake` after `battery reset`. Two full cycles ran, so the hysteresis re-arms. **The mechanism was checked, not just the marker**: `mScreenBrightnessOverrideFromWindowManager=0.00195` while blanked — the device's backlight *floor*, not off, which is why the black render in `body.too-hot` is load-bearing rather than decoration (ADR 0005 said as much; this measures it). **Its own acceptance was wrong and is fixed**: `screen=thermal` is a prefix of `screen=thermal-clear`, so the unanchored `grep -q` would have passed on an implementation that only ever logged the clear — the fourth line now anchors with `$`, and `MarkersTest` asserts the collision so it cannot be rediscovered from a green test. That is the fourth acceptance block in this repo that passed while proving less than it claimed. **The arbitration is one expression in one method**, `MainActivity.applyScreenState`: `lit = online && !tooHot`. The mechanisms deliberately are not shared — the PC releases `FLAG_KEEP_SCREEN_ON` and lets Android take the display, heat zeroes the window brightness with the Activity foreground *so that something is still running to notice the cooling*. One ordering trap handled: `ACTION_BATTERY_CHANGED` is sticky and lands in milliseconds while the first PC probe takes up to the connect timeout, so a thermal verdict can arrive before any PC state. Before the first probe the PC half reads as online — `onCreate`'s own stance — and the keyguard flags are left untouched until the service has actually spoken, or a thermal reading would have latched `setShowWhenLocked(true)` for a state nobody reported. `ThermalState` takes `nowMs` and **ignores it**, documented in the javadoc: the hysteresis is a pure function of temperature and the previous verdict, and the parameter is there because every state class here takes its time as a parameter and a future dwell rule would otherwise change the signature at every call site. `batteryWarm` is gone, replaced by `tempClass` returning one of three bands — two colours need two thresholds, and a pair of booleans that must not both be true is a state machine in the wrong file. `BatteryReading.plausible` became package-visible so "good enough to render" and "good enough to act on" cannot drift apart. **Reviewed before merge, nine findings, seven applied.** Three were one defect: the verdict was dispatched on every battery broadcast rather than on a change, so a charging phone drove a window update seven times a minute forever — two binder calls and an unconditional `dispatchWindowAttributesChanged` each time — including through the offline stretch T5.6 exists to keep quiet. It is edge-driven now, and `setPanel`'s replay serves the late window, which is what that replay is for. **The marker was in the wrong place and the review found the sequence that proves it**: get hot overnight with the PC away and `screen=thermal` was logged while nothing blanked — the display was already out — then the morning's login brought the panel up black with only `screen=wake` in the log. It is emitted from `setBlanked` now, where the panel's appearance actually changes, which is what ADR 0012 promises the marker means. Heat's veto also stopped consulting the PC: `setBlanked(tooHot)`, not `online && tooHot`, or a device that crossed 45 while offline came back lit at 46 degrees. The page stops its 1Hz clock under either cause of black, not just the PC's — the thermal one is the more cost-sensitive of the two, since the whole point is a device working too hard. **TT.6's own acceptance was failing on `main` and protecting nothing**: `grep -rn 'state=\|screen='` fires on any javadoc that names a marker, and this repo's javadoc names them constantly; it had three hits. It matches quoted strings now, which is the property that was meant — no marker *built* outside `Markers.java` — and prose may name them freely. Two findings were declined with reasons recorded in the code: the constants `BLANK_AT_C` and `BATTERY_HOT_C` genuinely are one decision in two languages with nothing tying them (there is no build step in `web/` to tie them with, so each now names the other and says what breaks), and `ThermalState` still acts on a single sample — a battery thermistor is slow and damped, and a dwell rule would be policy invented past the ADR to fix something nobody has seen, at the cost of delaying the case that matters. **Reviewed twice, and the second review found that the first fix did not do what its own commit message said.** Moving the marker to `setBlanked` was supposed to stop it claiming an event nobody could see, and it did not: heat's veto does not consult the PC, so crossing 45 °C with the display already out still logged `screen=thermal`, and the morning login still brought the panel up black with only `screen=wake` beside it. **The marker now reports the conjunction** — `online && tooHot`, "heat is why the panel you are looking at is dark" — and it is emitted by `PanelService`, the only component holding both halves. That also fixes the second finding: `blanked` was a per-Activity field, and MIUI relaunches the Activity on every wake from doze, so one thermal event logged twice. Its falling edge has two causes that the log tells apart by what sits next to it: alone the device cooled, paired with `screen=sleep` the PC left and now owns the dark. Three smaller ones: a dead local left by the first fix, `plausible()` documented as rejecting a zeroed struct when it accepts 0.0 °C as a real reading (now says so, and names the single-sample exposure that follows), and `CLEAR_AT_C`'s rationale written backwards — it claimed the panel returns still amber, when 38 is below the 40 warning and it returns in its normal colour, which is the right behaviour and now says why. **Verified on the device across all three states**: online at 46 °C gives exactly one `screen=thermal`; heating with the server killed gives none, because the PC owns the dark; and restarting the server logs `state=online`, `screen=wake`, `screen=thermal` in the same millisecond. **Not done: the manual check.** The temperature was injected, never real. Warming the phone in its stand and watching the DEVICE line go amber then red *before* the screen goes black is the half that proves the blanking is legible, and it needs an afternoon and a warm room |
| TT.7 | Espresso-Web assertions | todo | |

### Tooling: `e2e/layout/` (no task number — it arrived with T6.1)

A layout harness, deliberately recorded here rather than given an invented task id. It drives
Firefox over Marionette on the host (no phone, no adb, standard library only), measures
`web/index.html` at the phone's real 872x392 viewport and exits non-zero if any section is off
screen or clips its own content. `python e2e/layout/check_layout.py`, and
`--extra-css FILE` tries a size change without editing `web/`.

It exists because the fifth card hung off the bottom of the screen for two tasks while every
screenshot looked fine. Three things in it are worth more than the code: it calibrates the
layout viewport instead of trusting `SetWindowRect`, which silently gave 306px of height
instead of 392 and would have passed a broken layout; it fails when a section renders **empty**,
because an empty card always fits and that is precisely how the panel looked acceptable before
T6.1; and it runs a stress payload as well as a served tick, because the typical tick is not
what breaks a layout.

**T6.2, T6.3 and T6.4 should all run it** — each changes sizes, and a size change is what puts
a card off screen. **TT.7** is its on-device counterpart: this harness cannot see the real font,
since Android resolves `sans-serif-condensed` to Roboto Condensed while the host falls back to
something wider, so its text widths are a conservative estimate rather than the truth.

## Phase 6 — Visual (parallel with 3–5, touches only `web/`)

| # | Task | State | Notes |
|---|---|---|---|
| T6.1 | Landscape layout, neon palette | done | 2026-09-16. All six acceptance commands exit 0 (`node --test` still 16/16; the task file's colour literals were updated with the palette). **Palette re-cut twice at the user's request**: cyan on violet-black -> pink/red -> the settled `#000000` ground with a `#D53FA7` accent. Pure black is load-bearing, not taste: this is an AMOLED showing one frame for hours, so `#000000` pixels are off - no power, nothing to burn in (ADR 0008, T6.2). Card fills were dropped for the same reason. `--accent-dim` `#BB81AA` is the accent *desaturated, not darkened*: it carries the smallest text on the panel, so it measures 6.8:1 on black against the accent's 5.1:1 - de-emphasis comes from chroma, never luminance. Up/down are separated three ways so they can never be two shades of one hue: hue (`--up` `#3FD56C` is the accent's exact complement, 138 deg vs 318 deg), brightness (10.9:1 vs 6.1:1), and the sign `format.js` already writes - any one surviving is enough, which also covers a red/green colour-blind reader. **The T2.3 clipping is gone, measured not guessed**: Firefox driven over Marionette with the layout viewport calibrated to exactly 872 x 392 (`SetWindowRect` sizes the *outer* window, so it iterates until `innerWidth/innerHeight` match - the first pass silently gave 306px and would have made every number meaningless), `documentElement.scrollHeight` is 392 against 620 before, and a sweep of every element under `body` returns nothing outside the viewport and no section whose `scrollHeight` exceeds its `clientHeight`. Verified on `mock.js` as served and on a stress payload (`Sao Jose dos Campos`, `Thunderstorm, heavy hail`, -10 to 42 degrees, a zero change, `SHIBAINU-VERYLONGNAME`, `STALE` forced visible, pt-BR date); also clean at 839x392 and 1024x500. Three traps paid for. `#panel`'s rows are `minmax(0, Nfr)`, never `auto`: with `auto` an extra ticker from server config walks the battery card off the bottom again, and tickers are config, not a rebuild. The clock is 60px, not the 64px first cut - off-device the stack falls through to a non-condensed fallback where `HH:MM:SS` is ~4.5em against Roboto Condensed's ~4.0em, leaving 4px of slack inside a `#sidebar` that clips; at 60px it measures 266px in a 296px box. And card titles are `::before` content because `app.js` clears each section with `textContent = ''`, so no `app.js` change was needed at all. **Two things to look at on the device, not settled here**: the user's "the four cards are in a good position" was said about the *old* build, where the cards were empty outlines in a 2x2 that only fits because they hold nothing - this layout is a 2-wide, 3-tall card block beside the clock, which is the only arrangement where all five fit populated, and he has not seen it yet; and `#D53FA7` is mid-luminance, so the 11px card titles at 6.8:1 are the thing most likely to be too dim across a desk (T6.3 owns that call - the fix is a lighter `--accent-dim`, never a brighter accent). **Traceability caveat, and it expires at the merge**: the first half of this work is not in a T6.1 commit. `web/index.html`, `web/css/style.css` and an earlier version of this row were picked up by two `git add -A` runs from other agents sharing the worktree, so on `wave/5-phone` they sit inside two commits titled `docs(android): ...`. Content was byte-for-byte what had been measured; only the history was wrong. Deliberately not split: the branch reaches `main` through `gh pr merge --squash`, which collapses it to one commit, so the misattribution never arrives there and rebasing a worktree three agents were writing to would have risked real work to fix a property the merge erases. **If you are reading this on `main`, the two short SHAs that used to be quoted here no longer resolve** - that is the squash, not a lost commit; `git log -S 'id="sidebar"' -- web/` finds the change in whichever history you are in. The parallel-agent hazard behind it is in the PR body |
| T6.2 | Glow, micro-animations, burn-in shift | done | 2026-09-20. The panel moves now: `offsetFor(now)` in `format.js` walks a seven-position cycle 4px up and left, `host.js` writes it into `--burn-in-x/y` on every tick, and one rule in `css/style.css` translates `body > *`. **Core, against the task file's `Files:` line**, and for the reason T6.6 moved the animation pause there: it is the page's half of a promise about hardware, and a theme that forgot it would look perfectly fine and quietly etch the display. Glow and the pulse are taste and stayed in neon. Three defects found by the checks rather than by the eye — see the wave 15 section |
| T6.6 | **Slow scroll when a card overflows** | done | 2026-09-20, wave 14. `overflowsBy` and `scrollPlan` in `format.js`; the rows moved into a `.scroller` inside a `.card-body` window in **both** themes, and the animation sits on an element `mount()` builds once, so the 60s rebuild never touches it — the task's step 4 asked for rows updated in place or an offset carried across, and neither is needed once the animated element is the one thing that does not get replaced. A card says `data-scroll` while it is hiding a row; `e2e/layout/overflow.js` is a third `check_layout.py` pass that fails in both directions. **The second acceptance line was replaced**: it could not fail, and what it asked for would have broken the feature and contradicted T6.1 — see the task file |
| T6.7 | **A theme boundary** | done | 2026-09-20. All four acceptance commands exit 0, and the manual check is stronger than it was written to be: **the neon render is byte-identical before and after the move** — `check_layout.py --screenshots` on a worktree at `main` and on this branch produce the same PNG for the stress pass (`md5 41dadf5b…`), because that pass pins the clock, the date locale and every value. "Compare two screencaps" became an md5. **Where the line ended up.** `js/app.js` keeps the bridge, the payload, the clock's timing and the screen state, and contains no element, id or class name — that is the acceptance grep, and it is met by having no DOM in the file at all rather than by hiding it behind a helper. `js/host.js` is the seam: the live stylesheet, the current theme object, the root element, the blackout attribute. `web/themes/<name>/` owns everything else. A theme is an object with two functions, `render(payload, root)` and `tick(now, root)`, and `host.js` is the whole of the machinery — no registry of hooks, no lifecycle, because there is one consumer and it is a page that renders a payload. **Three constraints shaped it, and two of them are not obvious.** *(1) `#clock` has to exist before the page finishes loading*: `MainActivity.onPageFinished` reads it out of the DOM and logs `panel=rendered clock=` (T2.2, ADR 0009), so every script is in `<head>` with `defer` and every packaged theme registers as it parses. A dynamically injected `<script>` — the obvious way to load only the chosen theme — runs after that point, and the marker would have reported an empty clock on a panel that was about to be perfectly fine. `index.html` therefore carries a two-line manifest per theme; adding a theme is a rebuild whatever happens, because its files have to reach `assets/` somehow, and **switching** between packaged themes is what must not be. *(2) Stylesheets switch on `media`, not on the `disabled` property.* `disabled` was dropped from the HTML spec, and a browser that ignored it would apply every theme's rules at once — breaking the default look in order to make a non-default one work. `media="not all"` is not optional and cannot be misread. Both stylesheets are fetched at load, so a swap costs no request and shows no unstyled frame. *(3) The blackout is core's, not the theme's.* `body.pc-offline > *` and `body.too-hot > *` went to `css/style.css` as one rule on `:root[data-panel="dark"]`: it is the page's half of a promise about hardware (invariant 3, ADR 0005; T5.5, ADR 0012), and a theme that forgot it or spelled its class differently would leave a lit panel against a sleeping PC and look like a bug in Java. `docs/THEMING.md` states the one thing a theme owes it — never `visibility: visible`, which un-hides a descendant of a hidden parent. **Selection is the `theme` key T3.12 parked**: it rides `/quotes`, `DataPayload` passes it through untouched, and only the page decides. The server has no idea which themes the installed APK was built with, so an unknown name falls back to `neon` and warns once — a typo costs a line in logcat, never a blank panel. Verified: `--theme definitely-not-a-theme` renders a PNG byte-identical to neon's. An absent or empty key is **dropped** from the payload rather than sent as `""`, so an older server on the PC takes the same path. **The plain theme is the proof, and it is not decoration.** Same payload, different markup: the change sits before the number it describes, headings are real elements instead of `::before` content, the battery is in the flow instead of positioned, the weather is three lines, and the row wraps onto two — because four narrow columns cannot hold a ticker and two numbers on one line, and at one line it rendered `BTC` as `B1`. No core change was needed for any of it, which is the only thing that shows the boundary is real rather than a directory rename. It is held to T6.3's 20px floor, which is why that task's grep is now `-r` over `web/themes/`. **`check_layout.py --theme` earned itself immediately**: it caught the plain clock clipping its own digits by 5px, invisible in a screenshot, and again by 2px after the first fix. `mock.js` and `stress.js` both read `?theme=` so the two passes measure the same theme — without that, the stress pass would have switched a `--theme` run back to the default and measured the wrong panel while printing the right name. **Four earlier acceptance blocks were repaired, and one of them was already broken before this wave** — see the section below. **The review found six things and all six were fixed before the merge.** Five were small and real — a dead `fallbackTheme` field whose comment claimed two readers it did not have; an unknown-theme warning that latched on a *boolean* rather than on the name, so the owner's second typo months later would have been silent while `config.example.toml` still promised a line in logcat; `--screenshots` filenames that ignored `--theme`, which silently overwrote the very PNGs this wave's byte-identical claim compares; a `MainActivity` javadoc still pointing at the `index.html` guard T6.7 deleted; and a `THEMING.md` list that promised layout coverage for `#shortcuts`, which `measure.js` does not measure. **The sixth changed behaviour**: `onData` called `render` and `tick` into a blacked-out panel, contradicting `THEMING.md` and `app.js`'s own argument about not writing to a hidden DOM. It matters under the thermal cutoff specifically, where the poll loop deliberately keeps running so the device can notice itself cooling (T5.5) — so every cycle rebuilt the whole panel into a hidden DOM on a device being blanked *for working too hard*. A payload arriving while dark is now held, and the latest one is drawn the moment the panel returns. **That fix is why `e2e/layout/check_blackout.py` exists.** The blackout used to be two class names in the panel's own stylesheet; it is now an attribute on `<html>`, a rule in core CSS and a hold in `app.js`, none of which shows in a screenshot and none of which had a command. It drives the real page and asserts the round trip on both causes, and it is mutation-tested in both directions — deleting the hold fails it on three lines, `visibility: visible` on two. **Not verified on the device**: nothing here has been run on the phone. The three device-facing claims are that `panel=rendered` still reads a real clock, that the neon theme is unchanged under Roboto Condensed rather than the host's wider fallback, and that the plain theme is legible at 50cm |
| T6.3 | Legibility on the physical device | done | 2026-09-16. Both acceptance commands exit 0, and T6.1's five re-run green. Driven by the user at the device rather than by a ratio: he called the card titles too small and the date "exactly at the limit of comfortable reading" - the date was 16px, which is why the task's 20px floor is the right number and not a round one. Four declarations violated it: date 16px, battery 17px, card titles 11px, STALE badge 11px. All now 20px; clock stays 60px and weather 24px. **The clock was not cut.** 20px titles nearly double a line that appears five times, and the room came from spacing instead: body padding 12->10px, `#panel` gap 10->8px, and the row split 1.22fr->1.3fr, which is where the three-row B3 card needed it. The task's own note says to resist shrinking things to fit more in, and the clock is what the panel is for. Title tracking went 0.22em->0.14em because wide tracking reads as a label at 11px and as a gap at 20px, and WEATHER stopped fitting its card. Prices are now bold - step 2 of this task's ordering, after size: the titles are the same size as the numbers beside them now, so hierarchy had to come from somewhere that costs no vertical space. **Re-measured, not assumed**: `e2e/layout/check_layout.py` exits 0 on both payloads, document exactly 392px in a 392px viewport, nothing outside it, nothing clipping its own content. Worst-case free space below the content: B3 6.9px, FX and CRYPTO 6.3px, DEVICE 8.5px, WEATHER 29.4px. That headroom is font-independent - every line-height in the file is a unitless multiple, so box heights are the same under the device's Roboto Condensed as under the host's wider fallback; only text *widths* differ, and those only shorten a label that already ellipsises. **Still open and genuinely human**: whether the 20px titles now read as titles rather than as one more data row, since they match the row labels in size and colour and are separated only by tracking and position. Contrast was deliberately not touched - the user reported size, so size is what changed; a lighter `--accent-dim` stays in reserve if dimness turns out to be separate. **Five levers were then measured rather than argued about** (`--extra-css`, stress payload, 872x392), after the user asked whether shrinking the WEATHER card would help: narrowing it to 170px, cutting it to one row, both together, narrowing the sidebar to 230px, widening the row split to 1.6fr, and cutting the clock to 40px. **The middle column is byte-identical in every one of them** - quotes h=140 free=6.9, fx and crypto h=108 free=6.3 - because `#panel`'s rows are `minmax(0, Nfr)`, so heights are fractional and never content-driven, and the two columns are vertically independent. Nothing in the right column can give vertical space to the middle one, and the clock is paying for nothing at all (the sidebar has ~244px unused). The only vertical budget is `392 - 2*body padding - 2*row gap`, both already spent. Three of the levers actively break: WEATHER at one row overflows by 57px under the stress payload **while passing the served one**, WEATHER at 170px clips its own longest word and pushes the battery line to three, and the 230px sidebar clips 36px off the clock - the T2.2 defect returning. Rows cannot wrap by construction (flex row, `nowrap` on all three spans, ellipsis on the label): measured row heights are [31, 32], one line each, in every scenario. The lever with real value is the opposite of the request - WEATHER wants **more** room, not less, and demoting the DEVICE card takes it from 256px to 372px with 87.3px free while nothing else moves. That is recorded in T5.4, whose own step 3 already asks for DEVICE to be small and in a corner. **Second round at the device: all three questions came back clean** - titles comfortable, titles read fine as they are, date better than before. No hierarchy problem, so the 5-6px of free space in FX and CRYPTO stays unspent, which is the right outcome with T3.4 and T5.4 still to put real content in those cards. One process note worth more than the code: a heading-rule change was built and measured against `titulo so uma linha`, which had been relayed as "the title reads as just another row" but actually meant "the titles fit on one line and are fine". Reverted in full (`f97f65c` then its revert; the stylesheet is byte-identical to `0d4e8e2`, which is the state the user approved). The ambiguity had been flagged before the work started, and the cheap move - one clarifying question to the human - was skipped in favour of proceeding on the likelier reading. When a human's verdict is ambiguous, resolve it with the human; do not pick a branch and spend measured headroom on it |
| T6.5 | **A sparkline beside every value** | done | 2026-09-19. Asked for at the desk, mid-wave. The series is **fetched, not accumulated**: the WebView reloads on every wake (ADR 0014) so a page-side buffer is lost exactly when the screen returns, and a server-side one dies with the login session, so the chart would restart every morning. Real daily closes instead, from the same key-free upstreams that serve the prices — and the two disagree about direction, AwesomeAPI newest-first against Binance oldest-first, which is the trap: drawing one without reversing renders a rise as a fall and nothing about the picture says so. Each has its own `normalise_history` and its own test. Its own cache at 6h, and it never marks the payload `stale` — a decoration on a row that already carries the number it decorates must not be able to call that number old. `sparklinePath` is pure and in `format.js`, scaled to the series' own min and max rather than to zero, because a currency that moved 0.4% is a flat line against a zero baseline: true about the magnitude, useless about the trend. B3 carries an empty series until a brapi token exists. Two layout facts the device taught: the crypto card has the panel's widest prices and no slack, so the sparkline shrinks before the ticker does (it rendered `B…` first), and `vector-effect: non-scaling-stroke` is load-bearing under `preserveAspectRatio="none"` |
| T6.4 | Night profile | done | 2026-09-21. Phase 6 is finished. The window rides `/quotes` as two strings and is compared against the **phone's** clock twice — `isNight` for the glow, `NightWindow.java` for the backlight — because the two mechanisms do not meet and a page cannot reach `screenBrightness`. Three things cost time. **(1)** `DataPayload.merge` rebuilds the payload key by key, so the first build had a correct server, a correct page and a correct predicate on both sides, no `night` in the merge, and a panel that simply stayed bright with nothing in logcat; the device acceptance is what found it. **(2)** The acceptance the task shipped with — `logcat -c && sleep 90 && grep night=on` — could not pass against a correct app: the marker is a transition. `e2e/check_night_marker.py` drives the window instead, both edges, running the server itself. **(3)** The page's half is `animation: none`, not the blackout's `paused`, because here the panel is visible and a paused pulse is one number frozen at its brightest until morning |
| T6.8 | **The weather card earns its space** | done | 2026-09-20, wave 14. `formatRange` kills `-12-42`; `weatherGlyph` maps the WMO table onto six drawn conditions plus a named `unknown` that draws nothing. The neon card is city, glyph + 48px temperature, range, condition, measured at 872x392 under the stress payload; the city wraps rather than ellipsising, because it is the one string on the panel a reader cannot reconstruct from a truncation and it is server config. The plain theme takes the same two functions and its own answer |
| T6.9 | **The scroll goes round, at a quarter of the speed** | done | 2026-09-21, wave 17. Asked for from the chair. T6.6's card walked down to its hidden rows and back at four seconds a row; it now goes round in one direction at sixteen. The loop is the list drawn twice with the box moved by exactly one copy, and the pitch is **measured off the clone rather than computed** — rows carry a border between them and none after the last, so a copy inside a pair is one border taller than a copy alone, and that pixel is a jolt every couple of minutes. `check_scroll.py` asserts it exactly, not within a tolerance, and was mutation-tested from both sides. `scrollPlan` loses its fourth argument with the holds it described |
| T6.10 | **The battery corner draws its two labels** | done | 2026-09-21, wave 17. Asked for from the chair. `BAT 87% · 31°C` spent four characters of the widest thing in that corner saying what a picture says at a glance. `batteryFields` splits the line and `formatBattery` composes its string from it, so the two cannot drift. The battery draws its own charge, to the body's **inner** edge — a 1.6-unit stroke sits half outside its path, so a bar drawn to the coordinates vanishes under its own outline above about 80%. `unplugged` stays a word: there is no picture for "this phone is running its own battery down" that a stranger reads the way they read a battery outline. Turning the line into a flex row took its wrapping away and `check_layout.py` caught it at once |
| T6.11 | **Every word the panel shows, in the panel's own language** | done | 2026-09-21, wave 17. Asked for from the chair, after `Light drizzle`. A table per language in `format.js`; `language` rides `/quotes` beside `theme` and `night`, so a panel in another country is a restart of the server and never a rebuild. The fallback is **pt-BR and not English**, and the device's own locale is deliberately not consulted. `DEFASADO` rather than `DESATUALIZADO`, and the badge from 20px to 17: it shares a strip with the weather card's title and neither word is fixed any more. **It also found two blind spots in `measure.js`** — a `::before` has no DOM node, and the ink walk started at a section's *descendants*, so the clock, the date, the badge and all four card titles were invisible to the overlap check |
| T6.12 | **The right column becomes two cards, and the device line moves under the date** | done | 2026-09-21, wave 18. Asked for from the chair, three complaints about one card. The condition line went — the glyph beside the temperature was already saying it, and the words stay in `format.js` as the glyph's `aria-label` rather than being deleted. The battery and the handset's temperature left the weather card's foot for a line under the date: two temperatures in one box is a question, not a diagnostic, and the sidebar is the part of the panel that is about the machine. The right-hand track is a nested `1fr 1fr` grid holding WEATHER and a reserved AGENDA card for T9.1 — nested, because #panel's own rows are 1.3fr/1fr/1fr and any pair of them would split that column 58/42. **The card lost half its height and the type paid for it**: the temperature is 44px rather than 48, and the stress payload leaves **6.6px free** where T6.8 had 72 — `.w-body` measures 136.4px in the card's 143px content box, over Marionette. The row first said 12px, from a probe whose overflowing `scrollHeight` had dropped the card's own 5px bottom padding; the review of the wave caught it in `theme.css` and this row carried the optimistic number a commit longer. `measure.js` measures `#agenda` like any other section but lets a `data-reserved` one hold no text, and `agenda` is the first **optional** id in that list: `plain` has no such card and is not failed for it. Two harness faults found on the way — `report()` crashed with a `TypeError` on a section measure.js could not find, i.e. exactly when the panel is most broken; and the README's overlap regression recipe had stopped reproducing anything, because the line it grows out of its column is in the sidebar now |
| T6.13 | **At night the sky is not a sun, and the moon has a shape** | done | 2026-09-21, wave 19. Asked for from the chair with the panel lit: the card drew a **sun** for `Predominantemente limpo` in the dark. `is_day` rides the weather object, and so does the moon — both inside `weather`, so `DataPayload.merge` carries them with no Java change. **The phase comes from the USNO** (`aa.usno.navy.mil/api/moon/phases/date`, no key), asked for as an API rather than as arithmetic; the mean synodic model survives as the fallback and says `source: "mean"` out loud. Measured against two outside sources for 2026-09-22T00:27Z: USNO 10.875 d, moongiant 10.77 d / 83%, this 10.88 d / 84%, fallback 10.16 d / 78%. **The moon ended up permanent** rather than night-only, also from the chair — the phase as a filled path over a ring of the whole disc, plus the lit percentage, on the min/max line where the card had width to spare and so costs it no height. Raised 22 → 28 → 34px across three deploys with the check re-run each time. A clear night draws **stars**, not a moon, because drawing it twice would be the card saying one thing in two sizes. Two window constants were wrong first: six phases from 45 days back spans 44, so the window could end before today and every panel would have run on the fallback looking exactly as if it had not |
| T6.14 | **The jump, and the loop at night** | done | 2026-09-21, wave 19. Two complaints from the chair, neither a bug: the panel doing what it was written to do, decided for a panel this is not. **The "pulada" was the anti-burn-in shift** — measured, not guessed: eleven screenshots 28s apart, the whole panel moving (-8, +2) physical px in one frame, every four minutes. Not the scroll's seam, which was the first guess and was ruled out by logging the pitch on the device for six minutes at a constant `94.00`. The table is now 22 steps over 20 positions with **every step exactly 1px, the wrap included**; the band is 5x4 because a closed tour of a 5x5 grid cannot exist, and it is 22 steps rather than 20 because 20 minutes divides a day and the panel would have stood at the same offset at the same hour for ever. **The night rule went**: `[data-night] body * { animation: none }` stopped the cards at 22:00, the owner took it for a fault, and invariant 3 means the dark room it protected has somebody awake at a machine in it. `check_night.py`'s question 2 was **inverted rather than deleted** — a card that stops at night is now a regression. The value pulse fires at night as a side effect, which the old rule had suppressed entirely |
| T6.15 | **The chance of rain, beside the city** | done | 2026-09-22, wave 19. Asked for from the chair with the moon already on the card: a percentage beside the city, right-aligned into a column with the moon's, **no word, with a rain icon**. The data exists but not where you would look: `current` has `precipitation`, `rain` and `showers` — millimetres already fallen — and **no forecast at all**; the probability is a `daily` field, checked against the live endpoint. Today's max rather than the current hour, and the two are not close (98% against 31% at 2026-09-22T00:00): the card is already day-scoped and a glance must not change the scale of its numbers between lines. **The float is the whole of the layout** — a flex row failed the stress pass, because the drop took 60px of the first line and `SAO JOSE DOS CAMPOS` then needed a third, running 201px of content into a 180px box and drawing the range over the AGENDA card at seven burn-in offsets. A float costs only the lines it overlaps, which is also why the icon is 24px and not 26: at 26 it reached into the second line and the same failure came back. Two rounds of feedback from the chair — the icon was too small, and a bare drop "fica parecendo umidade", so it reuses the set's own cloud-and-rain shape. `formatIllum` became `formatPercent`: two formatters with one body is two places for the `--%` decision to drift |

## Phase 7 — Packaging

| # | Task | State | Notes |
|---|---|---|---|
| T7.2 | Wireless adb from the container | blocked | 2026-09-23, wave 22. **The container half is answered and the answer is "do not"**, which turns the task's step 4 fallback into the recommendation. Three measurements. The image does ship adb (1.0.41 / 37.0.1) via `platform-tools`, so that was never the question. `host.docker.internal` is a **Docker Desktop** invention and does **not resolve on Docker Engine** — it returned nothing here, and `docker/compose.yml` now maps it with `extra_hosts: …:host-gateway`; that line is a prerequisite of TT.7's `make connected`, which was written against a name this machine did not have, and whose only symptom would have been a Gradle task that could not find a device. Then the one that decides it: **adb cannot listen on a single interface** — `adb -a -L tcp:172.17.0.1:5037 nodaemon server` exits with `listening on specified hostname currently unsupported`, so the only server a container can reach is `adb -a` on `0.0.0.0:5037`, which is unauthenticated adb over the whole LAN. With that running the container does attach, so the route works and costs more than it is worth. Recorded in `docs/INSTALL-PHONE.md` and in TT.7's notes, where it changes a design. **Blocked on the phone half**: pairing is *Developer options → Wireless debugging → Pair device with pairing code*, tapped on the device, and the acceptance needs an authorised device — the one here answered `unauthorized` over USB and then dropped off. Neither is doable from a checkout |
| T7.4 | **Phone setup a stranger can follow, checked against the official docs** | done | 2026-09-27, wave 29. `docs/PHONE-SETUP.md` is the device-neutral half and `docs/INSTALL-PHONE.md` kept the vendor recipe; the split is **enforced rather than intended** — the acceptance greps the new file for the vendor's name and fails if it appears, which is the one assertion here that cannot pass by accident. Six `developer.android.com` citations for the four claims that get repeated wrong, and where the platform documents nothing the page says the behaviour was *measured on one device* and gives the command that measures it. The verification commands matter more than the granting: every grant silently resets on `adb install -r`, which is how they were lost twice. Lands **`scripts/check_links.py`**, which T7.3's acceptance has been calling since it was written and which did not exist — a network failure is reported apart from a 404 and gets its own exit code, because a contributor offline must be able to tell "you broke a link" from "you are offline". It found the original document's two step 6s |
| T7.5 | **Running it locally, for a contributor with no phone and no LLM** | done | 2026-09-27, wave 29. `docs/RUNNING-LOCALLY.md` in three tiers by **what the reader owns**, not by what the project contains: a browser alone reaches a moving panel because `mock.js` decides by `location.protocol` and the file that ships is the file you open; Python adds real data with nothing to install; Docker and a phone are the third tier and the page says plainly that a contributor without either still has a completely green `make check`. `docs/REQUIREMENTS.md` carries twelve versions and the single file that decides each, kept honest by **`scripts/check_requirements.py`** — the build is the truth and the page follows, so a bump in `docker/Dockerfile` turns it red at the moment the page is cheapest to fix. The dependency inventory is written as a constraint contributors must not break rather than as a boast. README gained a Quickstart, and two sentences that had said "nothing is built yet" through twenty-eight waves are gone |
| T7.6 | **Contribution guide, commit and PR templates** | done | 2026-09-27, wave 29. `CONTRIBUTING.md` argues maintenance rather than braces, and its teaching material is this repository's own comments — `BatteryReading.ABSENT`, `DataPayload.merge`, the eleven vtable placeholders. **`scripts/check_commit_msg.py` is the authority and the hook is three lines that call it**, so CI and the hook cannot disagree; `make hooks` installs it. The interesting part is what the checker refuses to do: Title Case is detected by **density** (half the words capitalised) rather than by counting capitals, because `MIC` and `POST` are acronyms and `Gradle`, `PcPoller` and `Linux, macOS and Windows` are proper nouns — the first two cuts of that rule flagged four legitimate subjects in this repo's own log. The cost is asymmetric: a false positive teaches `--no-verify` and after that the hook checks nothing. The acceptance runs it over the last thirty subjects, which is what makes the convention honest. Attribution trailers are rejected outright. PR template asks the two unusual questions this project has always answered: verified on the device versus reasoned about, and what was deliberately left out |
| T7.7 | **Opening the repo: contributor strategy and settings** | blocked | 2026-09-29, wave 36. Five of seven acceptance lines pass: `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, fetched, contact filled), `SECURITY.md`, `CODEOWNERS`, a device-report template and a chooser pointing questions to Discussions, the scope section at the top of `CONTRIBUTING.md`, labels and Discussions applied with `gh`, and three good-first-issues from the backlog (#49, #50, #51). **Blocked on the visibility flip**: branch protection answers 403 on a private repository on GitHub Free, so its two lines wait. The command is in `docs/MAINTAINING.md`, to run first after the flip |
| T7.8 | **Everything GitHub gives a public repo for nothing** | done | 2026-09-26, wave 25. Not a rewrite of `ci.yml` — TT.9 owns it; it gained `concurrency:` and SHA pins and nothing else. `lint.yml`, two jobs: `lint` (ruff installed in the job and never in `server/`, `node --check` over `web/` instead of ESLint because there is no `package.json` by design, PSScriptAnalyzer on `install_task.ps1`, shellcheck) and `guards` (every guard script that exists, plus `make lint-selftests`). **`scripts/check_ci_hygiene.py` is the deliverable**, six rules, each mutation-tested by its own `--self-test`. Three departures from the task file, each argued in the file that makes it: the SHA rule has **no `actions/*` exemption** — this repo pins those too, and an exemption is a decision the checker has to keep making right; dependabot covers **docker** as well, because `docker/Dockerfile` pins its base by digest and a digest is exactly the pin nobody updates by hand; and **CodeQL and dependency-review are absent rather than broken** — both need a public repo or Advanced Security, `code-scanning/default-setup` answers 403 here, and a check that cannot pass teaches everyone to scroll past it. `docs/MAINTAINING.md` carries the three steps that turn them on at T7.7's flip and says why the whole setup is free only while the repo is public. Rule 5 splits in two on purpose: **named in the Makefile** always, **run by a workflow** only for the guards `make check` reaches, because `check_branch_base.py` is green by construction on a runner and a green tick that means nothing is worse than none |
| T7.9 | **A design review of the seams, before strangers arrive** | done | 2026-09-27, wave 30. `docs/DESIGN-REVIEW.md`. The method was **four contributor walks** — add a theme, add an action, add a market, add a second weather provider — and every finding came from a walk rather than from reading. Adding a theme is a directory and two lines because `host.js` is a registry; adding a **market** is four places in `server/server.py` that are not near each other, and a contributor who finds three gets a row with no sparkline or a stale badge that never fires; adding a second **weather** provider has no seam at all — it is an `if` inside `App.weather()`, which is the worst answer of the four and the exact question the task's manual check asks a stranger. **The payload question got a definite answer**, which the task demanded: a comment is not the best available, because this one has now failed in the file it is written in; the shape exists in four places and nothing compares them, and one generated fixture with one assertion per layer closes it without a schema library or a build step. Three findings filed as T10.1–T10.3 and **no code changed** — a review that also rewrites is a review nobody can check. The document's other half is the eight things that look wrong and are load-bearing, because half its value for a newcomer is knowing which oddities to leave alone |
| T7.10 | **The sweep: what is in the tree, and what is in the history** | done | 2026-09-28, wave 33. `scripts/check_secrets.py` looks for **shapes**, not words: PEM blocks, ssh keys, JWTs, `AKIA`, `ghp_`, `xox`, `AIza`, bearer headers, an assigned secret-looking name, long hex and high-entropy runs — plus two rules that are not about credentials at all, the non-placeholder LAN address and **anything tracked that `.gitignore` excludes**, which `git add -f` and a rename past a rule both do silently. **Two halves, exiting differently**: the tree exits 1 (delete it) and the history exits 3 (rotate it), and 3 is the *worse* of the two so that `make check`, which runs the tree half only, cannot be made green by a fix that changes nothing in any clone. **Proved before it was trusted** — two fake credentials committed to a throwaway branch and *deleted in a following commit* were found anyway, named by blob, exit 3; branch deleted, sweep green. A scanner that has never found anything is indistinguishable from one that cannot. `scripts/secrets-allowlist.toml` refuses an entry with no reason or one that allows a rule everywhere, and `where` marks a decision that differs between the halves — which the real LAN address needed, being out of source now and still in those two files' history. **Result: no credential in the 336 tracked files or in any of the 1,080 blobs.** Acted on: the address left source for the placeholder, and seven `.gitkeep` files that had been holding open directories with content for weeks. Kept with a reason each: the address in prose, the adb serial, the home paths in the login-scope fixtures, **the author's email in all 164 commits**, the pinned digests, and `WINDOWS-NEXT-SESSION.md` while T3.8 is blocked. The history sweep is its own CI job for one reason, `fetch-depth: 0`: the guards job fetches thirty commits, and a sweep of *the history* over a shallow clone is a green tick that means "we looked at the last thirty". `docs/PRE-PUBLIC-SWEEP.md` is the record T7.7 needs |
| T7.3 | Pre-public review: secrets, README, screenshots | done | 2026-09-29, wave 37. All six acceptance lines exit 0. README final pass (multi-OS, multi-PC, the decisions as built, a Status that names the undiagnosed Windows autostart), the owner's photo in `docs/images/panel.jpg` with its metadata stripped, and the sixteen ADRs read against the code (ten amended, mostly missing back-links). The manual check, a stranger reading it, has not happened |
| TT.8 | `e2e/run_e2e.py`, five scenarios | todo | Needs TT.6 |
| TT.9 | CI workflow | done | 2026-09-24, wave 23. The bootstrap skeleton was `workflow_dispatch` only and had drifted for twenty-two waves — a workflow nobody runs is green forever. Now push and pull_request, three jobs, `permissions: contents: read`. **The task's real subject is `scripts/check_workflow.py`**, which reads ci.yml and the Makefile and fails on any difference: the command CI runs must be the same string the Makefile runs, with exactly one allowed difference — the `$(DC)` container prefix, dropped because a runner is disposable where the Windows host is not (ADR 0003). No PyYAML: this project takes no dependencies, and the reader **fails loudly on a shape it cannot parse** rather than returning an empty result that reads as agreement. Two rules came out of running it rather than writing it. `connectedAndroidTest` matched inside the comment *explaining* its deliberate absence, so the scan is comment-aware — the alternative was deleting the comment or gutting the rule. And a **`working-directory:` is now itself a violation**: `./gradlew test` from android/ and from the root are the same string and not the same command, so the old job's `working-directory: android` made the whole comparison a lie; the run steps sit at the root where the `gradlew` shim lives. setup-gradle gets no `build-root-directory`: the first cut passed one and the run went green while the action printed "Unexpected input(s)" and ignored it — the input belongs to the older gradle-build-action, and v4 caches the Gradle User Home, which is the same directory whichever subproject invoked it. A green check with a silently discarded input is this wave's own subject arriving in its own workflow. **`--self-test` found a bug in the reader on its first run** — `value.strip("'\"")` ate the trailing quote of `node --test "web/test/**/*.test.js"`, leaving an unterminated string — which is the argument for writing it first. 18 rules, and `make lint-workflow` runs both halves, so `make check` is what catches the next drift. CI does **not** run the guard scripts; that gap is T7.8's and is named in the script |

## Phase 8 — Shortcuts (v2)

The feature T3.7 reserved a route for and T6.1 left a hole in the layout for. Asked for on
2026-09-20: two buttons under the clock, bottom-left, one to mute the PC's audio and one to mute
its microphone. It spans all three layers, which is why it is a phase and not a row in phase 3
or phase 6.

| # | Task | State | Notes |
|---|---|---|---|
| T8.1 | **`POST /action/{id}` actually acts** | done | 2026-09-26, wave 26. **ADR 0015 first**, before `server/actions.py` existed, as the task file demands — the server has no authentication and every other route only answers a question, so what the endpoint may do was written before there was an implementation to defend. Two toggles, `mute-audio` and `mute-mic`; `shutdown`, `sleep` and `lock` are absent because the honest threat model is that anyone on the LAN can repeat an action as often as they like, and adding one is a change to the ADR rather than to a table. **The catalogue is in code and config can only switch its entries on and off** — a config that could name a command is a remote shell with extra steps, and it moves the security argument out of the reviewed repository into an untracked file nobody reads, which is why the earlier `ARCHITECTURE.md` sketch of "a Steam URI or an executable path from config" was dropped rather than built. **The order of the checks is the security property**: an id that is not enabled returns 404 having run *nothing at all*, and the tests assert that on the fake runner's call count, because a status-only test cannot tell 404-before-spawning from 404-after. `action_id()` widened from "no `/` and no `?`" to `[a-z0-9-]` — an allowlist of characters in front of an allowlist of names, so the promise that nothing is interpolated does not rest on the lookup being written carefully. `actions` went from a reserved table to a list of names and **an empty table still loads**, because `config.example.toml` shipped `[actions]` and an update that refuses to start is worse than a shape change (T3.13 from a direction it cannot see). An unknown name is fatal *before* `--check-only` returns, which is what the launchers and `after_update.py` run. Linux was exercised for real: both toggles moved `wpctl get-volume` and came back |
| T8.2 | **Two buttons under the clock** | done | 2026-09-26, wave 27. **Verified on the device**, not only in tests: SOM and MIC render in the `#shortcuts` strip T6.1 reserved six phases ago, `action=mute-audio result=ok` reaches logcat, and the PC's sink and source actually move. The hard part was invariant 1 as the file said: the page cannot make the request, so a tap crosses into Java through the app's **first inbound bridge**, and `Actions.resolve` returns the app's *own constant* rather than the caller's string — asserted with `assertNotSame`, which is why the class exists instead of a `contains` at the call site. `addJavascriptInterface` is safe here only because the WebView loads one URL from the APK's own assets with mixed content refused, and the call site says so. **Dead offline structurally**: the POST rides `DataPoller`'s executor, which exists exactly while the PC is online, so step 3 is a property of where the code lives. **The button shows the last result, never a state** — the panel cannot know whether the PC is muted, and one that says the mic is off while it is live is a privacy failure. `e2e/layout/check_actions.py` is the sixth browser check, mutation-tested three ways. **The bug the device caught**: `DataPayload.merge` rebuilds the payload key by key and nothing named `actions`, so the phone never saw it — with a correct server and a correct page. The file's own comment warned about exactly that, written when T6.4 shipped the identical failure |
| T8.3 | **MIC mutes every input on Linux and macOS** | done | 2026-09-27, wave 28. Linux does every input; **macOS cannot and ADR 0015 says so out loud** — `volume settings` knows one input and enumerating capture devices needs Core Audio through a compiled helper or a third-party binary, both outside the standard-library rule, so step 3's instruction to write the limit down rather than ship a guess is what happened. **A press stopped being one command**: the microphone on Linux is a listing, a direction, a set per input and a read per input, so `_SEQUENCES` sits beside `_TABLE` and holds the ids that are a *press* rather than a command — the row left in `_TABLE` is the press's first command, which is also exactly the binary the 501 path and the startup line probe for, so `candidates`, `describe` and `Unsupported` learned nothing new. **The direction comes from the inputs, and the first cut had that wrong** — it read `@DEFAULT_SOURCE@`, as the task file said to, and the review caught both halves of what that costs: a default that is a monitor is never muted by the press, so the button mutes for ever and never unmutes, and a default muted beside a live headset — the very state this task ends — answers "already muted" and the press *opens every microphone*. `state_from_sources` decides now, the same function the cross is drawn by. **Every name comes from `pactl`'s own listing**, which is ADR 0015's rule surviving the one id whose commands are built at run time, and a test asserts it argument by argument. `.monitor` sources are skipped — muting a loopback silences a screen recording and no person. **`wpctl` lost the microphone**: it has no verb for "every source", so keeping it as a fallback would put a PipeWire box quietly back to muting the default alone, which is the failure this task removes reintroduced by the kindness that was supposed to help; it keeps the speakers, and a box with `wpctl` and no `pactl` answers 501 with the startup line saying so first. **A partial mute is a failure, not a state**: one source refusing fails the whole press with its name in the message, and the read-back says `muted` only when every input is — a mix is `unknown`. Verified on the Linux desk, three real inputs and four monitors, through `POST /action/mute-mic` as well as the direct call. **macOS ran on 2026-09-29 (wave 34)**: both presses, directly and over `POST`, input 63 → 0 → 63 restored from the remembered level; only the default input moved, as ADR 0015 says |

## Phase 10 — What the design review found

Three findings from [T7.9](T7.9-seams-review-before-strangers.md), written as tasks rather than
as a diff. None of them is a rewrite; each is the shape "a contributor would do X and the code
makes X land in the wrong place". [docs/DESIGN-REVIEW.md](../docs/DESIGN-REVIEW.md) is the
argument behind all three.

| # | Task | State | Notes |
|---|---|---|---|
| T10.3 | **`lint-selftests` globs one directory and the repo has two** | done | 2026-09-28, wave 32. The glob is now per directory over `scripts/` and `server/`, sorted, and the loop **runs every script and fails at the end** rather than stopping at the first red one — found by review, after a red guard hid the very script this task exists to run; so `server/verify_login_scope.py --self-test` — the CLI entry point `docs/SERVER-SETUP.md` tells a person to run — is invoked by `make check` for the first time; `e2e/` stays out and the recipe says why, because its layout checks drive Firefox and exit 2 without a browser. Originally XS. `make lint-selftests` globs `scripts/*.py`, so `python server/verify_login_scope.py --self-test` is a command no target runs. **Smaller than first written**: the 97 cases are not orphaned — `server/tests/test_login_scope.py` imports `self_test_cases()` and `make check` runs it, and breaking a fixture goes red today. What is unguarded is the CLI entry point `docs/SERVER-SETUP.md` tells a person to run. The review's own first draft claimed otherwise and the correction is recorded in `docs/DESIGN-REVIEW.md` rather than edited out |
| T10.1 | **One description of the payload, and a fixture that fails when a key is dropped** | done | 2026-09-27, wave 31. `server/tests/fixtures/payload.json` is **generated by the server's own assembly** — not written by hand, or it would be a fifth copy with better branding — and the other two layers read it: `DataPayloadTest` asserts `merge` keeps **every top-level key** of the `/quotes` body, and a web test holds `mock.js` to the same set plus `weather` and `battery`, the two the phone folds in. The Android test's own string literal is gone; `Contract.java` reads the file, and the variants that used to be built by splicing text into that literal are built through `org.json`, because a generated file is free to change its spacing and every one of those would have become a no-op that still passed. **All three assertions were proved by mutation**: dropping `language` from `merge` reddens the Android suite, dropping `actions` from `mock.js` reddens the web suite, and renaming a key in `App.quotes()` reddens the server suite with the regeneration command in the message. The action id's three lists are checked the same way against `action_ids.json` — the duplication stays, ADR 0015 wants the phone's allowlist independent, and only the absence of a check that they agree was the defect. `DataPayload`'s warning comment now says what closed it. **The review found the weather half was not generated from the server at all**: the generator replaced `providers_openmeteo.normalise` rather than the fetch under it, so the file claimed `rainChance` (a key no server sends) and carried no `precipProb` (which every server sends and `format.js` reads) — and a key added to `normalise` would have regenerated to the same bytes. The seam moved down a layer: canned raw upstream bodies, the real `normalise` on top |
| T10.2 | **A market is one table entry, and weather gets a seam at all** | todo | `producers`, `wanted`, `_history_producer` and `key_for` are four places, and `key_for` is the one nobody finds. `actions.py` does the same job twelve lines away with a table every reader consults — this applies the pattern the codebase already has, and is explicitly not a plugin system or a provider base class. Weather needs its own small table or a written reason why one provider is enough; either answer is acceptable and it has to be written down |
| T10.4 | **The notes guard checks the heading and not the thing under it** | done | 2026-09-28, wave 32. A required section is now non-empty once HTML comments are stripped and reaches **twelve words** — a floor **measured, not chosen**: the smallest required section across the sixteen existing notes is 37 words, and a guard that fires on a short but honest section teaches people to pad, which is worse than the placeholder it catches. The `--self-test` it was one of four guards to lack lands with it: fifteen hermetic cases, one of them wave 30's note reproduced exactly. A sixteenth asserted *this repository's own notes pass* and **the review deleted it**: the design makes the guard red for the whole of every wave, `lint-selftests` stopped at the first red script, and T10.3's acceptance line therefore failed on the pushed branch — T10.4 silently deleting T10.3, which is this wave's own lesson arriving inside the wave. **Both offences are in the git record** — wave 30's *and* wave 31's notes carry `<!-- filled in after the review runs -->` in the first commit that created them, which is the evidence the task file asserted from one instance. The heading splitter tracks code fences, so a `## ` inside one is content. The redness is documented rather than designed away: a note is written before the review runs, so the guard is red from the moment `STATUS.md` carries the wave's section until the note is finished, and `docs/harness-notes/README.md` says so |

## Phase 9 — Suggested, not scheduled

Two improvements asked for on 2026-09-20, **after** every task above. Both are written down in
full so the idea is not lost and neither is started by accident. T9.1 was scheduled by the owner
for wave 38; T9.2 is still part of no wave.

| # | Task | State | Notes |
|---|---|---|---|
| T9.1 | **The next meeting, on the AGENDA card** | blocked | 2026-09-29, wave 38, PR #56. **Built and green; blocked on the owner's credentials**, and nothing else. [ADR 0017](../docs/adr/0017-calendars-are-personal-data.md) came before the code, and three corrections to this file came before either. The ADR number was 0017, because 0016 had gone to T4.5. The card was `#agenda`, which T6.12 had reserved, not the button strip. And Google's device flow allows no Calendar scope at all, so Google is loopback + PKCE and Microsoft keeps its device code flow. **Read-only is enforced in code**: `check_scope` runs on every token response, and a guard test allowlists every scope named in `server/*.py`. Tokens live in `calendar-tokens.json` (0600, atomic, compare-and-swap on rotation), never in `config.toml`. **DNS rebinding was the finding nobody asked for**: with titles on `/quotes`, any web page could have read them. Every route now checks `Host` and answers 421. Seven fresh-context lenses reviewed it, and every finding was applied. The worst was an `OSError` on the Microsoft token rotation, which escaped `load`, froze the previous agenda and retried on every poll. **Premises still unmeasured**: the fixtures are written from the docs, and no live response has been captured. `check_layout.py` did not run, because this Mac has no Firefox; headless Chrome's `measure.js` did, and it is clean. Left: create the Google and Entra clients, run `calendar_login.py`, run the opt-in contract, rebuild the APK once (`DataPayload`), then the manual check on the phone |
| T9.2 | **Spike: can the panel talk to an assistant for nothing?** | todo | A button to ask something out loud and hear an answer, with the whole pipeline on the PC — invariant 1 means the page cannot call anything. Time-boxed, produces `docs/spikes/2026-voice-assistant.md` and a throwaway prototype under `spikes/`, and is allowed to conclude *do not build this*. The unknown is whether offline STT, a small local model and offline TTS fit inside a latency a person will stand at a panel for; Claude and DeepSeek are the paid comparison, not the plan. Also has to answer the awkward ones: `RECORD_AUDIO` would be the app's first dangerous permission, and an unauthenticated LAN endpoint that runs a model and speaks in someone's room is not in ADR 0015's family |
| T9.4 | **Nobody else on the Wi-Fi can read the panel** | todo | Asked for on 2026-09-29, after T9.1 put meeting titles on `/quotes`: close both reading them by *asking* (any LAN device) and by *listening* (plain HTTP on WPA2-PSK). A spike on the Redmi comes first. **Try HTTPS with a pinned self-signed certificate plus a shared key** (stdlib `ssl`, audited crypto, `/app` off by default). If that fails on this phone, **the owner's design**: the `agenda` block encrypted end to end with the same key, where ADR 0018 must choose between relaxing stdlib-only for `cryptography` and an HMAC-SHA256 construction. After the owner's half of T9.1 |

## Resuming after 2026-09-29 (wave 38)

Wave 38 is **T9.1** on `wave/38-next-event`, PR #56. The owner asked for it over the recommended
flip to public: the next meeting from Google and Outlook, read-only, "tudo bem seguro". The code,
the ADR (0017), the docs and the review are done, and `make check` is green. **T9.1 is `blocked`
on credentials only the owner can create.**

**Next: the owner's half of T9.1**, in `docs/SERVER-SETUP.md` § Calendars. On the Windows PC:

1. Create a Google Cloud project with a Desktop client, and publish its consent screen as
   "In production". In Testing, the tokens expire every 7 days.
2. Create an Entra app registration for "any org + personal accounts", with public client flows
   on and `Calendars.ReadBasic`.
3. Fill in `calendar_accounts` and the client ids in `config.toml`.
4. Run `python server/calendar_login.py google --account personal`, and the same for each
   Microsoft account.
5. Run `RUN_CONTRACT_TESTS=1 python -m unittest discover -s server/tests -t . -p "contract_calendar*.py"`.
   Its first run is the first measurement of the providers' shapes. If it is red, the fixtures
   are wrong, not the tests.
6. Rebuild and install the APK once (`DataPayload` passes `agenda` now).
7. The manual check in the task file: a real event ten minutes out, then revoke access and
   watch the card fail alone.

**Then T9.4**, written after the wave at the owner's request. It covers whether anyone else on the Wi-Fi can read
the titles: a TLS spike on the phone first, and the owner's end-to-end design as the fallback. The owner will
start it after connecting the calendars.

The flip to public is still the owner's call, and nothing in this wave changes it.
`calendar-tokens.json` is gitignored and in the secret sweep's forbidden names.

### What is still only true on this desk

- **Every provider shape is a premise.** The fixtures are hand-written from Google's and
  Microsoft's references, and the contract test has never run against a live account.
- **`check_layout.py` has not run for T9.1**, because this Mac has no Firefox. Headless Chrome's
  `measure.js` is clean for both themes, both languages and three fixtures, with this Mac's fonts.
- **A work tenant may refuse consent** to an unverified app. Whether an employer's calendar may
  sit on a home panel is the employer's policy, and ADR 0017 says so.
- **The review's security lens pressed `mute-audio` four times on this Mac.** It was testing the
  Host check on a scratch server started from the example config, which ships with actions on.
  Four toggles is an even number, so the audio state should be where it was.
- The `make` targets call `python`, and this Mac has only `python3`. The wave ran through a
  scratchpad symlink. The first command of `make wave-start` failed without it.
- Everything carried from wave 37: the work email in `refs/pull/46..48/head`,
  `~/Downloads/keystore.properties`, and T4.5's move between two live PCs.

## Resuming after 2026-09-29 (wave 37)

Wave 37 is **T7.3** on `wave/37-pre-public-review`: README final pass, the sixteen ADRs read
against the code (ten amended), and all six acceptance lines green.

**Next: the flip to public, which is the owner's call.** T7.3 is done; nothing else blocks it.
Straight after the flip, run the two commands in `docs/MAINTAINING.md` (branch protection, then
private vulnerability reporting), which closes T7.7. No new task is recommended before that.

### What is still only true on this desk

- The work email in `refs/pull/46..48/head` on GitHub: a GitHub Support request.
- `~/Downloads/keystore.properties` with the signing passwords: the owner deletes it.
- T4.5's move between two live PCs, and the rest carried from wave 36.

## Resuming after 2026-09-29 (wave 36)

Wave 36 is **T7.7** on `wave/36-opening-the-repo`, after a history rewrite that put all 181 commits
under the owner's personal email. Everything a private repository allows is applied; the rest is
two commands in `docs/MAINTAINING.md` that answer 403/404 until the flip.

**Next: T7.3**, the pre-public review. The secret sweeps and the link checks already pass. What is
left is the README's final pass, reading the ADRs as an outsider, and **a photo of the panel on
the phone in its stand**, which only the owner can take. Then the flip, which is irreversible and
is the owner's call, followed at once by the two commands above. That closes T7.7.

### What is still only true on this desk

- **The work email survives in `refs/pull/46..48/head` on GitHub.** Only GitHub Support can purge
  it; the owner files that request before or after the flip.
- `config.toml` was deleted on the Mac; the agent reads `config.json`, which now holds the brapi
  token at mode 600.
- `~/Downloads/keystore.properties` still holds the signing passwords in plain text, outside the
  repository. The owner deletes it.
- T4.5's move between two live PCs, and everything carried from wave 35, unchanged.

## Resuming after 2026-09-29 (wave 35)

Wave 35 is **T4.5**, the panel following more than one PC (ADR 0016), on `wave/35-two-pcs`,
stacked on wave 34's branch. Code, build and JVM tests are done and green. The phone half is not.

**The phone runs the two-PC build.** With the Windows PC off it went online through the Mac in under 20 s. **Next: T4.5's other half**: Build with `PC_IP=<windows>,<mac>`, install, log out
of whichever PC the panel is on, and watch for `pc answered at` with no `state=offline`. Then T7.3.

### What is still only true on this desk

- **The Mac can build release APKs now**: the keystore is in the repo (gitignored) and `.env` has the
  signing values, copied from `keystore.properties` by a script that never printed them.
- `DataPoller` and the presses following the active host are pinned by the device block only.
- Everything carried from wave 34 is carried unchanged.

## Resuming after 2026-09-29 (wave 34)

Wave 34 was **the first Mac**, on `wave/34-macos-validation`. The repository runs on macOS now:
`make check` is green on Apple Silicon, T3.10's shape half and the macOS mute presses have run
on real hardware, and `after_update.py` has a Darwin branch. The note is
`docs/harness-notes/2026-09-29-wave-34.md`.

**Next: T7.3**, unchanged from wave 33 — the pre-public review, then T7.7. Nothing here moved it.

### What running it found that reasoning had not

The row for T3.10 said "Plist and docs ship anyway", and the plist did not exist. Writing it and
running it on the Mac found three defects that 97 green fixture cases had not: an XML comment the
verifier could not parse, a `launchctl print` parser that read a nested block's `type =`, and a
firewall message naming the wrong binary. The review then found that `after_update.py` read the
file on disk instead of the loaded job, and that nothing pinned the `-k` in `kickstart -k`.

### What is still only true on this desk

- **T3.10's behaviour half** — that nothing answers at the login window — needs a logout and a
  second device. Still `blocked`, now on that and not on "no Mac".
- **This Mac's firewall blocks the LAN.** `/ping` is up on `127.0.0.1` and down on the LAN address
  until `Python.app` is allowed in System Settings. That is a manual grant.
- **The agent here points at a scratchpad copy of the example config.** The session could not
  write `server/config.toml`; the owner copies it and re-runs `sh server/install_agent.sh`.
- **The Linux restart has the gap macOS just closed**: nothing pins that `systemctl --user
  restart` restarted anything, and nothing checks the pid. Small, and not done here.
- `server/config.json` mode 0644, the Windows installer's TOML branch, `WINDOWS-NEXT-SESSION.md`,
  the twenty taps and the phone on adb: carried unchanged from wave 33.

## Resuming after 2026-09-28 (wave 33)

Wave 33 is **T7.10**, on `wave/33-pre-public-sweep`. The repository has been looked at — every
tracked file and every one of the 1,080 blobs in the pack — and `docs/PRE-PUBLIC-SWEEP.md` is
the record of what was found, what was changed and what is being published on purpose.

**Next: T7.3**, the pre-public review, which this wave was written to run before. Its acceptance
now has two lines it did not have (`check_secrets.py`, both halves) and both pass today, so what
is left of it is the README's final pass, the screenshots, and the reading a person does. Then
**T7.7** makes the repository public — the irreversible one. **T10.2** (the market table) is the
only other open task and nothing waits on it.

### No credential, and that is a result rather than a relief

The tree is clean and so is the history. What makes that worth anything is that the scanner was
made to fail first: two fake credentials went into a throwaway branch, were **deleted in a
following commit**, and the history half found them anyway, named the blob and exited 3. Then
the branch was deleted and the sweep went green. `git rm` removes nothing from a clone, which is
the whole reason the history half exists.

### The two halves exit differently, and the worse one is 3

A finding in the tree is a deletion. A finding in the history is *rotate the credential* — the
blob is in every clone already and no deletion reaches it. `make check` runs the tree half only,
so the history half had to exit with something `make check` cannot turn green: it is 3, which is
the more serious of the two, and the docstring says so because `check_links.py` uses 3 for the
milder case and a reader will assume the convention holds.

In CI the history sweep is **its own job**, for one reason: `fetch-depth: 0`. The guards job
fetches thirty commits, and `git rev-list --all` over a shallow clone walks what was fetched and
reports "nothing found" about everything else. That is this repository's recurring failure shape
— a green tick whose label claims more than the check did — and it would have shipped here
unnoticed.

### The allowlist is the deliverable, not the scanner

Thirteen entries, each with a reason the loader requires: an entry with no reason, or one that
allows a rule everywhere, makes the file unusable and the script exits 2 rather than passing.
The `where` field was added mid-wave when the sweep produced exactly the case it is for — the
LAN address is out of source now and still in those two files' history, and *accepting it there*
is a different statement from accepting it in the tree.

The review then produced the case a second time, from this wave's own commit: the scanner's
sample table was committed whole before it was split into parts, so `check_secrets.py`'s own
blob trips ten rules for ever. Allowed, `where = "history"`, with a reason that says how wide
the entry is and why the tree half is the gate that matters.

The awkward one is recorded rather than solved: **the author's name and email are in all 164
commits** and going public publishes them. Rewriting that is 164 commits and a force-push;
changing it going forward is one `git config`. It is the owner's call and it is now a choice
rather than a discovery.

### What is still only true on this desk

- **`server/config.json` is still mode 0644** and holds the brapi token. One `chmod 600`; T7.3
  wants it. Carried from wave 19 through 32. The sweep confirms the file has never been
  committed, which is the part that would have been permanent.
- **The Windows installer's TOML branch has still never been run.** No PowerShell here; T3.8.
- **`WINDOWS-NEXT-SESSION.md` ships unless T3.8 clears first.** It is live triage and deleting
  it would lose the only write-up of that failure. T7.3 looks again.
- macOS mute (T8.3), the twenty taps, and the phone on adb: carried unchanged.
- **A scanner reads shapes.** A password that looks like a word goes straight through it, and
  nothing here changes that; the defence is still that secrets live in gitignored files on the
  PC.

## Resuming after 2026-09-28 (wave 32)

Wave 32 is **T10.4 and T10.3**, on `wave/32-guard-reads-the-label`. Both are the same defect in
two places: a check that exists and a check that runs are different things.

**Next: T7.10**, the pre-public sweep. It was asked for from the chair on 2026-09-27 and it runs
**before T7.3 and T7.7**, which are the only two tasks left between here and a public repository.
Then **T10.2** (the market table), which is phase 10's remainder and its largest; nothing is
waiting on it.

### The floor is measured, and that is the only defensible kind

`## What the review found` had to be *written*, not merely present, and the whole question was
what "written" means without teaching people to pad. The answer came from the record rather than
from taste: the sixteen notes that exist were measured, the smallest required section in any of
them is 37 words, and the floor is twelve — a third of the smallest thing anybody has actually
written here, and still clear of the shortest section the README sanctions, a wave with nothing
outstanding saying so in one line.

A character count would have been the same rule with a number nobody could argue with or against.

### The task file asserted from one instance and the record held two

T10.4 was filed off wave 30's note. Wave 31's resume section said it happened again, so the claim
was checked against `git show` on the first commit of each note rather than repeated: both carry
`<!-- filled in after the review runs -->` verbatim. That is the difference between a guard
written for an anecdote and one written for a pattern, and it cost one command.

### T10.4 deleted T10.3, and the review is what noticed

The self-test shipped with a case asserting *this repository's own notes pass*. It was green when
it was written and red three commits later, because adding this very section to `STATUS.md` is
what makes the guard red until the note is finished — and `lint-selftests` stopped at the first
red script, so `server/verify_login_scope.py` never ran and T10.3's acceptance line exited 1 on
the pushed branch. One task quietly undid the other, with `make check` red for a reason that
looked like the documented one.

Two rules came out of it, and both are now in the code that would have to break them:

- **A self-test is hermetic.** It answers whether the code is right; `make lint-notes` answers
  whether the notes are. A case that reads the repository is the second question wearing the
  first one's clothes.
- **A check that runs N things runs all N.** Stopping at the first failure is the "a self-test no
  target invokes" defect arriving through the back door, in the target written against it.

### The guard is red mid-wave by design, and that is now written down

A note is created before the review runs — the section cannot be filled before there is something
to fill it with — so from the moment `STATUS.md` carries a wave's `## Resuming after` section
until the note is finished, `make check` is red and names the unfinished section. The rule was
left as it was and `docs/harness-notes/README.md` gained the paragraph, because a reminder that
reads as a bug gets suppressed and a reminder that is explained gets answered.

### What is still only true on this desk

- **`server/config.json` is still mode 0644** and holds the brapi token. One `chmod 600`; T7.3
  wants it. Carried from wave 19 through 31.
- **The Windows installer's TOML branch has still never been run.** No PowerShell on this
  machine; T3.8 is the task that proves it on the box.
- macOS mute (T8.3), the twenty taps, and the phone on adb: carried unchanged.
- **Nothing measures whether the twelve-word floor is right.** It is defensible against the
  sixteen notes that existed on the day. If a later note is honestly shorter than a sentence and
  the guard fires, the floor is wrong and lowering it is the correct fix, not padding the note.

## Resuming after 2026-09-27 (wave 31)

Wave 31 is **T10.1**, on `wave/31-one-payload-description`. The payload shape is written once, by
the server, and the other two layers are held to it.

**Next: T10.4**, which is small, was found by a review of the wave that filed it, and **happened
again in this one** — the notes guard reads the heading and never what is under it, so this
wave's note also shipped `## What the review found` as an HTML comment with `make check` green.
Twice in two waves is no longer a curiosity. Then **T10.3** (the `--self-test` CLI path)
and **T10.2** (the market table), in either order; T10.2 is the largest and the least urgent.

Phase 7 still needs **T7.7** (opening the repository) and **T7.3** (the pre-public pass). Those
two are the whole distance to a public repo and the record says nothing else blocks them.

### What the fixture is, and what it is not

It is **generated from `App`'s own assembly** with every provider replaced, so it reaches no
network and produces the same bytes on every machine. Hand-writing it would have created a fifth
copy of the shape with better branding.

It is *not* a schema. There is no validation language here and nothing new on any dependency
list — the whole mechanism is one committed JSON file, a Python test that regenerates it, and one
loop per layer over the keys it contains. That was the constraint the standard-library rule left
available, and it turned out to be enough.

The history had to be primed **synchronously** in the generator. `warm_history()` starts a thread
per market on purpose — a sparkline must never make a payload wait — and a fixture generated
against a thread is one that is sometimes written without its sparklines, with the difference
invisible in the diff.

### Three mutations, because an assertion nobody has seen fail is a decoration

- `payload.put("language", …)` removed from `merge` → `mergeKeepsEveryKeyTheServerSends` fails,
  naming the key.
- `actions: ACTIONS` removed from `mock.js` → the web test fails saying the PC sends it and the
  mock does not.
- `payload["actions"]` renamed in `App.quotes()` → the server test fails with the regeneration
  command in the message.

Each was backed out from a `cp` copy, never with `git checkout --`.

### What is not proven

- **Only the payload's top level is compared across layers.** The review's own finding, and it
  survives the fix: `mock.js` having `precipProb` and `moon.illum` right was luck rather than a
  guard, and the same is true of every row shape under `quotes`, `fx` and `crypto`. The weather
  object is now checked against what `normalise` returns; the rows are not checked against
  anything.
- **The weather half was wrong until the review caught it**, in a wave whose whole claim is that
  the description comes from the server. It came from a stub of the function that decides the
  shape. Worth remembering when the next fixture is generated: *what exactly is being replaced,
  and does the thing under it decide anything?*
- **Nothing checks the fixture is regenerated when it should be.** The server test fails when the
  committed file has drifted, which is the guard — but a contributor who regenerates without
  reading the diff still ships whatever they changed. That is the same bargain every golden file
  makes and it is worth knowing.
- **The e2e path is untouched.** These are three unit suites agreeing about a file; the device
  still only proves itself by being installed, which is what found the `actions` bug in the first
  place.
- **`withBattery` has no contract assertion of its own.** `battery` is asserted in the web test
  as a key the mock must feed, and on the Java side only by the existing battery tests.
- macOS mute, the twenty taps, the phone on adb, `chmod 600` on `config.json`: carried unchanged.

## Resuming after 2026-09-27 (wave 30)

Wave 30 is **T7.9**, on `wave/30-seams-review`: `docs/DESIGN-REVIEW.md`, three findings filed as
T10.1–T10.3, and no code changed.

**Next: T10.1**, because it ends a class of bug that has shipped twice, and it is the finding of
the three that the record actually supports. **T10.3** is XS and can ride with it, but it is
smaller than this wave first claimed — the review's review proved the 97 cases are already run by
`make check`, and only the `--self-test` entry point is unreached. **T10.2** is the biggest and
the least urgent: nobody is adding a market this week.

Phase 7 still needs **T7.7** (opening the repository) and **T7.3** (the pre-public pass, which
now also owns deleting `WINDOWS-NEXT-SESSION.md` from the root — the review found it tracked and
it is a session hand-off note, not documentation).

### What the walks found that reading did not

The method was four contributor walks, and it is worth keeping: *add a theme, add an action, add
a market, add a second weather provider*, each traced file by file. Reading the layers explained
the findings; it did not produce any of them.

The result is an asymmetry nobody would have described from memory. `web/` has a registry, so a
theme is a directory and two lines. `android/` has its decisions in plain classes, so
`PanelService` can be 1,154 lines and hold almost none of them. `server/actions.py` has a
catalogue table that every reader consults. And the providers — **the thing a contributor is most
likely to touch** — have none of that: four scattered edit points for a market, and for weather
no seam at all.

### The payload question got a definite answer

T7.9 required one rather than a shrug: is the comment in `DataPayload.merge` the best available?

No. It has failed **in the file it is written in** — `night` in T6.4, `actions` in T8.2 with the
warning about the first sitting right above the line that dropped the second. That is the
strongest evidence a comment can produce about itself. The shape lives in four places and
nothing compares them, and one fixture generated by the server plus one assertion per layer
closes it with no schema library and no build step, which is what the standard-library rule
leaves available.

### What is not proven

- **The review's own manual check is unrun.** T7.9 asks for somebody who has never seen this
  project to be handed the review and `CONTRIBUTING.md` and asked where a second weather provider
  goes. Nobody has been. The findings are a walk done by the person who has read everything,
  which is precisely the reader whose instincts are least informative.
- **Four layers were not read evenly.** The walks pushed the attention into `server/` and the
  `web/`↔`android/` seam. `format.js` at 1,068 lines and the six browser checks were read for
  shape, not adversarially. A second pass starts there.
- **No finding was verified by breaking anything.** F1 rests on two shipped bugs in the record
  rather than on a fresh reproduction; T10.1's acceptance is where that gets proved.
- macOS mute, the twenty taps, the phone on adb, `chmod 600` on `config.json`: all carried
  unchanged from earlier waves.

## Resuming after 2026-09-27 (wave 29)

Wave 29 is **T7.4 + T7.5 + T7.6**, on `wave/29-docs-cluster`: the documentation cluster, three
tasks and three guards. A stranger can now clone this repository, reach a moving panel with
nothing installed, find out which versions matter and why, and read what will send their pull
request back.

**Next: T7.9**, the design review of the seams — asked for from the chair this session and
scheduled deliberately after the guide that gives it a yardstick. Then T7.7 (opening the
repository) and T7.3 (the pre-public pass) close phase 7.

### Three guards arrived already wired, which was the trap working

Wave 25 set it: rule 5 of `check_ci_hygiene.py` goes red the moment `make check` reaches a
`scripts/check_*.py` that no workflow runs. `check_links.py`, `check_requirements.py` and
`check_commit_msg.py` all landed in the Makefile and in `lint.yml` in the same commit, because
the alternative was a red build. That is the second time a guard written two waves earlier has
paid for itself without anybody remembering it existed.

Each of the three carries a `--self-test`, so `lint-selftests` discovered them by grep with no
list to update — and each self-test caught a real defect in its own script before any document
used it: a table separator read as a requirements row, a `report()` that printed a wall of text
into the test output, and `/dev/stdin` refused because it is a pipe and not a file, which is the
exact invocation T7.6's own acceptance uses.

### The link checker's first run found the split it was written for

`docs/INSTALL-PHONE.md` had **two step 6s** — the vendor battery list and Android's battery
exemption, the two the document itself warns are constantly confused, numbered identically since
the day they were written. Nobody reading it had noticed. It is now one numbered list of seven.

It also found the thing worth knowing before T7.7: **GitHub answers 404, not 403, for a private
repository's pull requests**, so an anonymous checker cannot tell "deleted" from "not yours". The
harness notes and task files are full of such links. So `make check` runs the local half over
every Markdown file in the repository and CI runs the full half over the documentation a reader
actually follows. When T7.7 makes the repo public that distinction disappears and the CI list
should widen to `MARKDOWN`.

### The review found the two worst defects in the prose, not the code

Eight findings. The two that would have cost a contributor most were instructions they would
follow and fail: a Quickstart that only works on macOS, inside the block promising "nothing
installed", and a troubleshooting row recommending `python -m http.server -d web` for a blank
panel — which loads the page and silently kills the mock feed, because `mock.js` only runs from
`file:`. Both were written in a session that had read the relevant guard the same day.

Three more were in the new guards and would have bitten quickly: a 429 from a shared CI runner
reported as a dead link (the script had already separated `unreachable` from `dead` for exactly
that reason and then did not use it), `git commit -v` failing on the content of the diff because
the scissors line is not a comment, and a hook that picked `python3` where everything else here
says `python` — which on Windows means `make hooks` succeeds and every commit afterwards fails.

**The transferable part: the guards were reviewed as code and the documents were not reviewed at
all.** A document is an interface, and this wave shipped it with less adversarial reading than a
function would have got. T7.9 inherits that lesson, and both unrun manual checks below are the
same gap seen from the other side.

### What is not proven

- **Neither document has been read by a stranger.** T7.4 and T7.5 both ask for exactly that —
  hand the page to somebody with a different phone, or a machine that has never built this, and
  watch where they stall. Both manual checks are unrun, and the defect they are meant to find is
  invisible from here by construction.
- **The commit hook has never rejected a real commit.** It is installed in this worktree
  (`make hooks`) and its rules were exercised against the history and the self-test; no
  contributor has hit it.
- **The issue forms have never been rendered.** GitHub parses `.github/ISSUE_TEMPLATE/*.yml`
  server-side, and a schema mistake shows up only in the UI — which needs the repository to be
  public, or a visit to the Issues tab that nobody has made.
- **macOS mute is still unrun**, and the default-input limit is in ADR 0015 (wave 28).
- **The twenty-taps check is still not done**, carried from wave 27.
- **The phone was not touched**, carried from wave 22: TT.7, TT.8, T2.4 and T7.2 all wait for it.
- `server/config.json` is still mode 0644 and holds `actions` as well as the brapi token. One
  `chmod 600`; T7.3 wants it. Carried from wave 19.

## Resuming after 2026-09-27 (wave 28)

Wave 28 is **T8.3**, on `wave/28-mute-every-mic-linux`. The MIC button now mutes every input on
Linux the way it does on Windows, and the macOS limit is written into ADR 0015 instead of being
left as a comment. Phase 8 is closed again.

**Next: T7.4 + T7.5 + T7.6**, the documentation cluster — unchanged from wave 27's
recommendation, which this wave interrupted for a reason given below. None of it needs the
phone, Docker or a public repo, and it produces the three guard scripts T7.8's `guards` job is
missing; rule 5 of `check_ci_hygiene.py` goes red the moment either task lands a
`scripts/check_*.py` that `make check` reaches and no workflow runs, so they cannot arrive
unwired.

Phase 9 (T9.1, T9.2) is unblocked and still "suggested, not scheduled".

### Why a new task jumped the recommendation

Wave 27's `Next:` line pointed at the documentation cluster and was right when it was written.
It was written before the Windows box was ever used, and the first press of MIC there muted the
default input while the owner was talking into another one — a 200, a cross on the button, and a
live microphone. Windows was fixed the same day and **T8.3 was filed for the other two
platforms**, which is a row the wave-27 section could not have known about.

Two things made taking it first the obvious call rather than a judgement one. It is the failure
ADR 0015 singles out as worse than having no button at all, and it is a privacy claim the panel
was making incorrectly on this very desk. And **this session is the Linux desk** — three real
capture devices and four `.monitor` loopbacks plugged in — so the manual check the task asks for
could actually be run, which is the thing a Windows session could not do.

### What the fix cost the shape of `actions.py`

`run_action` ran one argument list. The Linux microphone cannot: nothing knows what to mute
until `pactl list short sources` has answered, so a press is a listing, a direction, a
`set-source-mute` per input and a `get-source-mute` per input. `_SEQUENCES` now sits beside
`_TABLE` for the ids that are a press rather than a command, and the row left in `_TABLE` is the
press's *first* command — which is also exactly the binary the 501 path and the startup line
probe for, so nothing that reads the table had to learn a new shape.

The rule that survived the change is the one that matters: **every name comes from `pactl`'s own
output and never from the request**, asserted argument by argument rather than by intent, on the
one id whose commands are now built at run time.

### The review found the fix pointing at the wrong device

The direction was read from `pactl get-source-mute @DEFAULT_SOURCE@`, which is what the task
file said and what shipped green, manually verified on real hardware. The default source is not
necessarily one of the sources the press touches: if it is a monitor, its state never moves and
the button mutes for ever; if it is muted beside a live headset — **the exact state this task
exists to end** — the press opens every microphone in the machine.

It is the same shape as wave 27's bug one layer up. There, one line between three green layers;
here, a source of truth sitting beside the thing it claims to describe. Both passed every test
and both passed a manual check, because the author was thinking about the normal case — three
microphones in the same state, a default that is one of them.

**When a press acts on a set, the state it reads has to be the state of that set.** Reading a
neighbouring thing that is usually the same is how a fix for "the wrong device" ships with the
wrong device still in it. The review also found that `pactl`'s answers are translated
(`Stumm: ja` on a German desktop), which the old locale-independent `toggle` never cared about
and a press that parses the mixer's words does — `LC_ALL=C` on every child, and it is a
consequence bullet in ADR 0015 so it is not read as tidiness and removed.

### What is not proven

- **macOS is still unrun, and now also unimplementable within the rules.** The default-input
  limit is in ADR 0015; nobody has pressed the button on a Mac at all.
- **The twenty-taps check is still not done.** Carried from wave 27. It is more interesting than
  it was: a Linux microphone press is now eight `pactl` invocations, not two, so a finger on the
  button for twenty presses queues eight times as much work behind the poller's single thread.
  `/ping` was observed answering between presses this session, which is not the same thing.
- **`invoke`'s `rejected` path has still never run on the device** — unit tests only, because no
  theme can produce an id outside `Actions.ALLOWED`.
- **The phone was not touched this wave.** TT.7, TT.8, T2.4 and T7.2 have been waiting for it
  since wave 22; wave 27 found it back on adb as `303f1f9c` and the cable was not used here.
- **`check_pulse.py --theme plain` still fails on `main`**, unchanged from wave 27: `plain` does
  not pulse and the check says itself that such a theme should be skipped. One line in a task
  file, not a bug.
- `server/config.json` is still mode 0644 and holds `actions` as well as the brapi token. One
  `chmod 600`; T7.3 wants it. Carried from wave 19 through 27.

## Resuming after 2026-09-26 (wave 27)

Wave 27 is **T8.2**, on `wave/27-two-buttons`. The panel can mute the PC it sits next to, and
phase 8 is closed.

**Next: T7.4 + T7.5 + T7.6**, the documentation cluster, which is now the only thing left before
T7.7 and T7.3. None of it needs the phone, Docker or a public repo. It also produces the three
guard scripts T7.8's `guards` job is missing — and wave 25 already wired the trap: rule 5 of
`check_ci_hygiene.py` goes red the moment either task lands a `scripts/check_*.py` that `make
check` reaches and no workflow runs, so they cannot arrive unwired.

Phase 9 (T9.1, T9.2) is unblocked — ADR 0015 exists — and is still "suggested, not scheduled".

### The chair changed step 7, and the fix was to stop guessing

After the buttons were seen on the panel, four asks came back: no caption, a bigger icon, **a
cross when the PC is muted**, and a border that was being clipped by `#sidebar`'s `overflow:
hidden`.

The cross contradicts T8.2 step 7 as written — *"shows the last result, not a live state"* — and
step 7 said that because every Linux mixer toggles in silence, so the state was not knowable.
The answer was not to relax the rule but to make the state real: **the server runs a second,
read-only command after the toggle** and reports what the mixer actually holds. ADR 0015 carries
the three limits that keep it honest, and the sentence step 7 exists to protect is untouched — a
button that says the microphone is off while it is live is still a privacy failure.

The clipped corner is worth one line of its own: the fix is 6px of clearance, and **6 rather than
less because the burn-in shift moves the whole panel up to 4px**. A 2px margin would have looked
right in a screenshot and brought the cut back for part of every cycle.

### The device caught a bug three green layers did not

T8.2 was written end to end, unit tested, exercised in two themes in a real browser by a new
harness check written for it, built, installed — and **drew no buttons at all**.

`DataPayload.merge` rebuilds the payload key by key, and nothing named `actions`. The server was
sending it, the page was ready to draw it, and the phone never saw the key. Every layer was
correct in isolation.

The file's own comment, written when T6.4 shipped the identical bug two waves earlier:

> **This copy is the whole of the wiring, and forgetting it is silent, and it is true of every
> line above it as well.**

It was read *after* the failure. A warning in the file a change has to touch is not a gate, and
this is the second time this exact one has been paid for. Two tests cover the key now and the
comment names both occurrences, which is the cheapest thing available and is not the same as a
check.

**The lesson for the next wave is narrower than "write a check":** the browser harness proved the
page, `./gradlew test` proved the classes, and neither could see the one line between them. The
five-minute device install is what closed it, and it was only possible because the phone came
back onto adb this session.

### The phone is on adb again, after five waves without it

`303f1f9c`, over USB, authorised. The record has said "the phone is not on adb" since wave 22 and
it has been blocking **TT.7, TT.8, T2.4 and T7.2** the whole time. It is worth taking those while
the cable is in — TT.8 in particular, because `e2e/run_e2e.py` now has an `action=` marker to
assert and no scenario for it.

Two things were observed on the device that are not tasks and belong somewhere:

- **The Activity had died on its own with the PC plainly online.** `PanelService` kept polling
  (`ping=ok` every 2s, uninterrupted), the screen was `Dozing`, and `am start` brought the panel
  straight back. That is the MIUI trap the root `CLAUDE.md` names — `FLAG_KEEP_SCREEN_ON` does not
  stop the battery manager freezing an Activity — seen with markers for the first time rather than
  reported from the chair.
- **`check_pulse.py --theme plain` fails on `main`** and was failing before this wave. `plain` does
  not pulse, and the check's own message says it should be skipped for such a theme. It is a task
  file that needs one line, not a bug.

### What is not proven

- **The twenty-taps check was not done.** Each button was pressed four times and the toggles all
  landed; nobody hammered one to watch `/ping` keep its beat while twenty presses queue on the
  poller's single thread.
- **`invoke` has never been called by anything but a finger and the browser stub.** In particular
  the `rejected` path — an id that reaches Java and is not in `Actions.ALLOWED` — has unit tests
  and has never run on the device, because no theme can produce it.
- **macOS and Windows are still unrun**, unchanged from wave 26.
  `tasks/T8.1-actions-execute.md` carries a seven-step Windows runbook, written this session and
  ordered so each step fails faster than the one after it.
- `server/config.json` is mode 0644 and now holds `actions` as well as the brapi token. One
  `chmod 600`; T7.3 wants it. Carried from wave 19 through 26.

## Resuming after 2026-09-26 (wave 26)

Wave 26 is **T8.1**, on `wave/26-actions-execute`. `POST /action/{id}` stops being a 501 and
starts muting this PC, and **ADR 0015** is the half that had to be written first.

**Next: T8.2**, the two buttons under the clock. It is the only thing T8.1 was blocking and the
task file says so in its own notes: *"the buttons are useless without it, and the temptation
while building them is to have the page do something else in the meantime."* The hard part is
invariant 1 — the page cannot make the request, so a tap has to cross into Java through the
app's **first inbound bridge**, and `invoke(id)` must match the id against a set Java already
knows rather than concatenating it into a URL. That is ADR 0015's rule made again on the other
side of the wire, and it is the reason to do it now while the argument is fresh.

After that the documentation cluster **T7.4 + T7.5 + T7.6**, which is the only thing left before
T7.7 and T7.3 — and which wave 25's `check_ci_hygiene.py` rule 5 has already wired: the moment
either lands a `scripts/check_*.py` that `make check` reaches and no workflow runs, CI goes red.

**Phase 9 is unblocked as a side effect.** T9.1 and T9.2 both declared `ADR 0015` as a prereq
and it exists now. Neither is scheduled — phase 9 is "suggested, not scheduled" — but
`check_status.py` no longer reports them as reserving a number.

### Writing the ADR first changed the implementation, which is the argument for the rule

`docs/ARCHITECTURE.md` had carried a sketch of this endpoint since the beginning: *"`id` indexes
a closed allowlist in server config that maps to a Steam URI or an executable path."* Writing the
threat model down killed it. A config that can name a path **is** a remote shell with extra
steps for anyone who can write that file, and worse, it moves the security argument out of the
reviewed repository into an untracked file nobody reads. The catalogue is in code now and config
only switches its entries on and off; the sketch is recorded as dropped rather than quietly
replaced.

The same order produced the `[a-z0-9-]` narrowing of `action_id()`. The ADR's promise is that
nothing from the request is ever interpolated — and the cheapest way to keep a promise like that
is to have nothing interesting survive the front door, rather than to rely on the lookup being
written carefully forever.

### The tests that matter assert on a call count, not on a status code

`404` for an id that is not enabled is easy to get right and easy to get subtly wrong: a 404
produced *after* spawning something passes every status-only test and fails the endpoint. So the
fake runner counts its calls, and three tests assert it was never called — for a disabled id, for
an id outside the catalogue, and for a `GET`.

Two more are worth keeping if the file ever shrinks. **The id never appears in any argument
list**, asserted for every action on every platform: that is the direct statement of "the id is a
key, not a value". And **`candidates()` returns a copy**, because without it one caller appending
to the list it was handed would extend the catalogue for the whole process.

A third was written, failed, and was replaced rather than relaxed: a scan for `{}` and `%s` in
every argument, meant to prove there was nothing to interpolate into. The Windows command is C#
and the test failed on `class MMDeviceEnumeratorComObject {}`. A bad proxy for a real property,
and the real property was available.

### One shell survives in the table, and it is named

The macOS microphone command is an AppleScript literal that calls `do shell script` to keep the
remembered input level in `dev.bosco.deskpanel`'s preferences — because `volume settings` has no
input toggle, and muting to 0 and unmuting to 100 hands somebody's carefully set level back as a
shout. It is a constant from end to end and the only value concatenated into it is an integer
AppleScript itself read from the audio API. The alternative was two commands per press and a
state machine in Python to sequence them: more moving parts guarding the same constant. Named in
the ADR, in the module, and here, because an unnamed exception is how a rule stops being one.

### What is only true on this desk

- **Linux is the only platform actually exercised.** Both toggles were driven through a real
  server on a spare port and observed moving `wpctl get-volume @DEFAULT_AUDIO_SINK@` and
  `@DEFAULT_AUDIO_SOURCE@` to `[MUTED]` and back. **macOS and Windows are written and unrun** —
  the macOS input-volume restore in particular has never executed anywhere, and it is the one
  branch with logic rather than a single call.
- **The `--serve` acceptance line needs port 8777 free**, and the installed user unit holds it on
  this machine. It was run against a temp config on port 8791 instead, which probes the same
  code; running the literal line means `systemctl --user stop desk-panel` first, and that takes
  the panel down while it runs. Noted in the task file.
- **The installed server is still running the old code.** It was started at login and holds
  `server.py` as it was then — `POST /action/mute-audio` against the live panel answers 501 until
  someone runs `python scripts/after_update.py`. That is exactly the failure T3.13 exists for,
  arriving on schedule.
- **The phone is still not on adb**, unchanged since wave 22. TT.7, TT.8, T2.4 and T7.2 need it.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants
  it. Carried from wave 19 through 25.

## Resuming after 2026-09-26 (wave 25)

Wave 25 is **T7.8**, on `wave/24-selftest-runner-and-ci-hardening`, PR #32 — and the branch name
is wrong because the wave started wrong. Read the next section before anything else.

**Next: T8.1**, unchanged from what wave 24's record already said and what this wave should have
done. It writes **ADR 0015**, which T9.1 and T9.2 are both blocked on, so it unblocks the whole of
phase 9 as a side effect. Read `## Why this is the first task where the server stops being
read-only` before writing any code, and do its steps in order: the ADR comes first, before
`server/actions.py` exists.

After it, the documentation cluster **T7.4 + T7.5 + T7.6**, which is what wave 24 recommended and
is now the only thing left before T7.7 and T7.3. T7.8's `guards` job runs every guard that exists;
`check_ci_hygiene.py` rule 5 fails the day T7.4 or T7.5 lands a `scripts/check_*.py` that `make
check` reaches and no workflow runs, so those two arrive already wired.

### This wave was built on a `main` four commits stale, and that is its real subject

The session opened with a git status showing `ace5f7e`, read the `tasks/STATUS.md` of that tree,
and took its `Next: TT.12 + T7.8` at face value. On the real `main`, **TT.12 had merged the day
before as PR #31**, and the newest commit was literally `docs: next session starts on T8.1`. TT.12
was rebuilt from scratch — the same two bugs, the same `lint-selftests`, the same `lint-status` —
and thrown away at the rebase. The chair caught it by asking *"a recomendação não era fazer a
8.1?"*, which is the only thing in the loop that did.

**This is the second time**, and the first fix was prose. PR #30 died the same way in wave 21, and
the response was a sentence in `CLAUDE.md` saying `git fetch` before you branch. It did not hold,
because a sentence is not a command with an exit code and everything else in this repo is.

So step 0 of *How to resume work* is now `make wave-start BRANCH=wave/NN-slug`: it fetches,
reports what `main` was missing, fast-forwards, cuts the branch, and prints the `## Resuming
after` header you are meant to read. `scripts/check_branch_base.py` is the half with the exit
code, and it was tested against the exact commit this session started from — it reports the four
missing commits and names the superseded `Next:` line.

**The first wiring of it could never fire**, and the review is what caught that. `wave-start` ran
the guard *after* `git merge --ff-only`, where `git log origin/main ^HEAD` is empty by
construction — so the fix for the failure that defined this wave was itself unable to fail. It
runs twice now: `--report` before the merge, which prints and never fails because being behind at
the start of a wave is the normal case, and a plain call after it as a post-condition. Writing the
check was not the hard part; wiring it where it can still be true was.

It is deliberately **not** in `make check`. A PR branch is behind `main` as a matter of course,
and a guard that goes red on every open pull request the moment `main` moves is the failure this
whole wave is about, one layer up.

### What T7.8 decided that the record had reserved for the chair

Wave 24 parked T7.8 on two questions and said neither was an agent's to answer alone. Both were
put to the chair and both were answered by ratifying what is in the branch:

- **the guards job runs the guards that exist**, which is the second of the two options wave 24
  itself wrote down. Rule 5 of `check_ci_hygiene.py` is what makes that safe: T7.4's
  `check_links.py` and T7.5's `check_requirements.py` cannot land unwired.
- **CodeQL and `dependency-review-action` stay off** while the repo is private. Neither was
  added-and-broken, no setting was changed, and no money was spent; `docs/MAINTAINING.md` has the
  three steps and the `gh api` call that turns them on in the same session as T7.7's flip.

The irreversible half was **not** taken: the repo is still private, because T7.3 is explicitly the
last look before it opens and is still `todo`.

### The review found ten, and the two it left were the two that mattered

Eight were applied by the review, two were left as design calls and both are now fixed. Besides
the `wave-start` ordering above: **rule 4 checked ecosystem names and never each entry's
`directory:`**, so a `gradle` entry pointing at `/` instead of `/android` would update nothing and
still print OK — the "looks like coverage and is not" that rule 4 exists to catch, inside rule 4.

Two of the applied eight are the same shape as this wave's own subject — a check reporting
something true about a tree it had quietly altered. `check_ci_hygiene.py` numbered lines *after*
stripping comments, so every violation was reported at the wrong line; and rule 5's "named in the
Makefile" half was a substring search over the whole file, so a guard mentioned only in a `help:`
echo and run by nothing passed. **Eight of the ten findings are in the two guard scripts this wave
wrote**, not in the workflows they guard.

The full list is in `docs/harness-notes/2026-09-26-wave-25.md`.

### Two things found on the way past, not fixed here

- **`lint-selftests` globs `scripts/*.py` only.** `server/verify_login_scope.py` has a 97-case
  `--self-test` and no target invokes it — which is TT.12's own finding, surviving inside TT.12's
  own fix. It is one glob; it belongs to whoever touches that target next.
- **`ruff` found three things on `main`** and all three are now fixed: an unused `import os` in
  `test_contract_helpers.py`, and two lines over 120 in `after_update.py`'s case table. The rule
  set is `E`, `W`, `F` and is deliberately small and green; `I` and `UP` are each a repo-wide
  mechanical diff and belong in their own commit.

### What is still only true on this desk

- **The phone is still not on adb**, unchanged since wave 22. TT.7, TT.8, T2.4 and T7.2 all need
  it, and the first step is the RSA prompt on the device.
- **T7.8's `## Manual check` was not done.** Nobody opened a pull request with a deliberately bad
  Python line to see what a reviewer sees before reading any code. Every job has been seen green;
  the reviewer's view of a failure has not.
- **The double `push` + `pull_request` run did not reproduce.** Wave 23 recorded two run ids per
  commit on #29 and asked for it to be settled deliberately. On #32 only the `push` runs exist and
  they are what the PR's checks point at. It was not investigated; it is recorded because the last
  record says the opposite.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants
  it. Carried from wave 19 through 24, still not done.

## Resuming after 2026-09-24 (wave 24)

Wave 24 is **TT.12**, on `wave/24-the-self-tests-nothing-runs`. Wave 23 recommended TT.12 + T7.8
and the order was load-bearing; TT.12 landed and **T7.8 was not started**, for two reasons in
its own header rather than anything found by running it.

**Next: T7.8 is blocked on a decision, not on work.** Both halves are in the note
(`docs/harness-notes/2026-09-24-wave-24.md`) and neither is a judgement call an agent should
make alone:

1. **Three of the five guard scripts step 7 names do not exist.** `check_links.py` (T7.4),
   `check_requirements.py` (T7.5) and T7.6's commit-message check are all unwritten, and all
   three tasks are declared prereqs of T7.8. Wave 23 assumed the five were there. Either T7.4-
   T7.6 come first, or step 7 is rewritten to run the guards that exist — which after this wave
   is every one of them, through `make check`.
2. **The repository is private, and T7.8 is titled for a public one.** Its step 1 is the
   argument: Actions minutes are unlimited on public repos and metered on private, CodeQL is
   free on public and paid otherwise, `dependency-review-action` needs Advanced Security. Steps
   5 and 8 would spend the owner's money and change repo-level settings.

**Superseded 2026-09-25, from the chair: next is T8.1.** The T7.x reasoning below still holds
and is what to come back to after it; T8.1 simply jumped the queue, and it earns the place —
**it is what writes ADR 0015**, which T9.1 and T9.2 are both blocked on, so it unblocks the
whole of phase 9 as a side effect.

Read `## Why this is the first task where the server stops being read-only` before writing any
code, and do its steps in order: **ADR 0015 comes first**, before `server/actions.py` exists.
This is the first route that changes the machine the server runs on, and the server has no
authentication by design (invariant 2, ADR 0004) — so the allowlist is the design and not a
detail, T3.7's constraint is *the request carries an id and nothing else*, and `mute` is in
scope precisely because repeating it is harmless while `shutdown` is not. Prereqs T3.7, T3.11
and T3.12 are all `done`; `Requires:` is none for the tests, a desktop session for the manual
check.

**The T7.x chain was unblocked on the way past, 2026-09-25.** `T7.4`'s `Prereqs:` said
`T2.4, T7.2` — both `blocked` on a phone nobody here can tap the RSA prompt for — which made the
whole `T7.4 → T7.5 → T7.6 → T7.7 → T7.3` chain read as unreachable. **Not one of T7.4's five
acceptance commands touches `adb`**; the phone is in its `## Manual check` only, exactly as its
own `Requires:` line said, and `docs/INSTALL-PHONE.md` already exists. `Prereqs:` is now `none`,
with the reasoning in the task file. This is the second time a `Prereqs:`/`Requires:` line has
been overstated in this repo — T7.1 recorded the first — so check the line against the
acceptance block rather than trusting it.

The original decision, still the right one once T8.1 lands: **T7.4 + T7.5 + T7.6**, the
documentation cluster T7.8 actually depends on — none of which needs the phone, Docker or a public repo. It
also produces the three missing guard scripts, after which T7.8's step 7 is true as written and
its `guards` job has five real commands to run instead of two.

The repo stays private for now. Making it public would make all of T7.8 free, and it was
considered and set aside: **T7.3 is explicitly the last look before the repo opens** — secrets,
README, screenshots — and it is still `todo`. Opening first would run that task after the thing
it exists to gate.

### A self-test no target invokes is a test suite with no runner

Two scripts, red for waves, each on the OS nobody checked them on. `after_update.py --self-test`
exited 1 on **Linux** because `python_for` used `Path`, which is `PosixPath` there, so a Windows
path came back unchanged; `check_status.py` exited 1 on **every** OS because it read `ADR 0015`
as a task id. Neither was run by anything.

The fix that matters is not either bug. It is `lint-selftests`, which discovers by
`grep -l -- '--self-test' scripts/*.py` rather than by a list, so the next script to grow a
self-test is covered by being written — and `lint-status`, so the fifth guard script is finally
in `make check` with the other four.

**An ADR is allowed to not exist yet.** `check_status` now understands `ADR NNNN` and
deliberately does not require the file: T9.1 and T9.2 are blocked on ADR 0015 being written, and
a prerequisite you have not met is the normal case. The shape is checked; the number cannot be.

### The backslash cost this repository time for the third time

Two independent instances in one wave, one written and one found. The new Makefile target was
drafted through a heredoc and every continuation collapsed; then the review found that the
continuations which *did* survive into the committed file would not have worked on this desk
either, because the worktree is CRLF and a backslash followed by CR is not a line join. `cat -A`
showed both; `sed -n` showed neither. The recipe now has no continuations at all.

Wave 20 found this in `sed` through Git Bash, TT.11 built the probe for it, and this session had
read both notes before adding a third case. The rule that follows is mechanical, because "be
careful" has now failed twice: **a file whose content depends on backslashes is edited with a
file tool, not through the shell, and it is read back with `cat -A`.**

### The shell ate the backslashes, one wave after the note about it

The new Makefile target was written through a heredoc and every `\`+newline continuation
collapsed, leaving a literal `
` in `check:` and the whole recipe on one line. `sed -n` showed
it as fine; `cat -A` showed the truth. Wave 20 recorded this trap in these words — *the agent's
own shell collapses a doubled backslash in the commands written to diagnose backslash handling*
— and this session had read that note before walking into it.

The rule worth keeping is mechanical, because "be careful" already failed: **a file whose
content depends on backslashes is edited with a file tool, not through the shell**, and it is
read back with `cat -A`.

### What the next wave inherits that is only true on this desk

- **The Linux half of TT.12 is unproven, and CI does not fix that.** No WSL, no Docker, no
  `make` here. The fix is sound by construction — no `Path` remains in the decision — and both
  cases pass on Windows, but nobody has watched them pass on Linux. The first draft of this
  section said CI would settle it; **it does not.** `ci.yml` runs the server suite, the web
  suite and `gradlew test`, and none of the three invokes `after_update.py --self-test`.
- So the wave fixed a test nothing ran, added the target that runs it, and **that target is
  still run by nobody but a human at this desk.** `make check` is the only thing that reaches
  the guard scripts, and no machine runs `make check` unasked. This is the gap T7.8 step 7
  closes, and it is a better argument for T7.8 than wave 23 had: it is now about proving a fix,
  not about tidiness.
- **A wave was wasted before this one.** The session opened by rebuilding T0.6 against a `main`
  four waves stale, against a snapshot that reads as current. PR #30 was closed and its branch
  kept. One `git fetch` before branching is the whole fix.
- **The phone is still not on adb**, unchanged from waves 22 and 23. TT.7, TT.8, T2.4 and T7.2
  all wait on the RSA prompt nobody can tap from here.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants
  it. Carried from wave 19 through 23, still not done.

## Resuming after 2026-09-24 (wave 23)

Wave 23 is **TT.4 + TT.9**, on `wave/23-contract-tests-and-ci`, PR #29. Contract tests against
the five real upstreams, CI on every push, and `scripts/check_workflow.py` to stop the two from
drifting again. **TT.12** was written, not executed: wave 22's record said the `--self-test`
finding needed a task file, and a resuming section is not one.

**Next: TT.12 + T7.8**, and the order inside the pair is load-bearing. T7.8's own row promises a
lint job that "runs the repo's own five guard scripts, which nothing runs today unless a human
remembers" — and two of those scripts are **red on `main` right now**. Add the job first and it
arrives red, which teaches everyone to ignore it, which is the failure the bootstrap `ci.yml`
already demonstrated for twenty-two waves. **TT.12 first, then the job that runs it.**

Everything else in the backlog needs the phone (TT.7, TT.8, T2.4, T7.2) or another machine
(T3.8's Windows half, T3.10's Mac), or is documentation waiting on T7.8 (T7.4–T7.7, T7.3).

Five rows stay blocked and none of them is blocked on work: **T2.4** and **T3.10** (no Mac),
**T3.9**'s human half, **T3.8**'s Windows half, **T7.2**'s phone half.

### A tool that catches CI overclaiming, caught overclaiming

`check_workflow.py` compares the command CI runs against the command the Makefile runs. The
review found three ways it counted a step that is **present** as a step that **runs**:

- **`continue-on-error: true`** on the android suite left the check returning zero problems. CI
  green on a red suite, while `make test-android` exits 1 on the same tree.
- **`if:`** does it the other way — `if: github.event_name == 'push'` on `assembleDebug` is green
  and runs no Gradle on a pull request.
- **a blank line inside a `run: |` block** closed the block, and every command after it matched
  no `run:` and was dropped, reported as CI not running something it runs two lines below.

The first two are banned outright rather than inspected, and that is the general rule this wave
is worth remembering for: **a check that tries to decide which conditions are harmless will one
day decide wrongly and say nothing.** The three layers here have no conditions to express.

### `gh run watch --exit-status` is not a gate on the workflow being correct

TT.9's own acceptance line proves the suites passed. It does not prove the workflow does what it
says, and this wave has the demonstration: the first android job passed **`build-root-directory:`
to `setup-gradle`, which is an input of a different action**. The run went green while the action
annotated that it had discarded the input. Nothing in the acceptance could see it; `gh run view`
by eye could, and does now, as a `## Manual check` in the task file.

Two annotations are still there and are **T7.8's**, not bugs: `actions/checkout@v4`,
`setup-java@v4`, `upload-artifact@v4` and `setup-gradle@v4` all target Node 20, which is
deprecated, and `ubuntu-latest` migrates to Ubuntu 26 on 2026-10-19. T7.8 SHA-pins the actions
anyway, so the version bump belongs in the same pass.

### What the contract tests actually pin, and what they cannot

Fifteen cases, green on 2026-09-24 against brapi, Binance, AwesomeAPI, open-meteo and the USNO.
**That is all a contract test ever proves**; their value is the run someone does in three months,
and the task file says to do it monthly.

Three of them go past "the key is still there", and those are the ones worth keeping if the file
ever has to shrink:

- **Binance's kline close is positional**, index 4 of a twelve-element array, and nothing in the
  response names it. An inserted column redraws every crypto sparkline from the volume, and
  nothing about the picture says so.
- **open-meteo's daily arrays are asserted to still align with `current.time`.** The timezone
  parameter failing does not error — it reaches the panel as a missing min and max.
- **the USNO window is asserted to still bracket now with two New Moons**, which the first cut of
  `LOOKBACK_DAYS`/`NUMP` did not, and the symptom is the moon quietly not being drawn.

### What the next wave inherits that is only true on this desk

- **The phone is still not on adb**, unchanged from wave 22. TT.7, TT.8, T2.4 and T7.2 all need
  it back, and the first step is the RSA prompt on the device, which nobody can tap from here.
- **TT.9's `## Manual check` was not done.** Nothing deliberately broke one test to confirm that
  only its job goes red. Every job has been seen green; the failure path has not.
- **`on: push` with no branch filter runs all three jobs twice for every PR from this repo** —
  two run ids per commit, visible on #29. The review declined to change it because it is a
  decision about what the trigger means rather than a bug, and TT.9 step 1 says push and pull
  request in those words. Worth settling deliberately, in the task file, before the repo opens
  and the minutes are someone else's.
- **`--fix` owns the working tree until it reports.** This session edited
  `scripts/check_workflow.py` while the review agent was writing to it and produced duplicate
  self-test cases; the review removed its own copies, kept the session's, and reported "another
  session is reviewing this same branch" — which was this session, failing to wait. Nothing was
  lost, and nothing except reading the case list would have caught it.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants
  it. Carried from wave 19 through 22, still not done.

## Resuming after 2026-09-23 (wave 22)

Wave 22 is **T3.6 + T7.2**, on `wave/22-the-apk-over-the-wire`. They pair by intent — both are
"get a build onto the phone without a cable" — and they came apart on contact: one landed whole,
the other split into a half that could be measured here and a half that needs a finger on the
device.

**Next: TT.4 + TT.9** — contract tests, opt-in, and the CI workflow. They pair for the same
reason the last two did: TT.9 has to decide which layers run without hardware, and TT.4 is the
layer that deliberately does not. Read `Prereqs:` rather than the phase order.

Five rows stay blocked and none of them is blocked on work: **T2.4** and **T3.10** (no Mac),
**T3.9**'s human half, **T3.8**'s Windows half, and now **T7.2**'s phone half.

### The route was small; what it dragged in was not

`/app` is twenty lines. Getting to it changed `route()`'s contract for every caller:

- **`route()` returns four values now**, because `Content-Disposition` is the difference between
  a browser offering to install an APK and saving a file called `app` with no extension, and a
  header is the router's business rather than the handler's. Nine unpackings in two test files
  moved with it. This is the wave-17 lesson in a smaller key — grep for the other readers before
  redefining what a function returns — and the grep was cheap because they were all tests.
- **`HEAD` did not exist.** `BaseHTTPRequestHandler` answers 501 to any method with no `do_`,
  so the acceptance line as written could never have passed. `do_HEAD` routes as GET and drops
  the body on the way out, which is what HEAD means and what keeps `Content-Length` honest.
- **The acceptance needed an assertion that did not exist.** `probe.py` read headers off the
  wire and threw them away. `--expect-header` is new, and it is the whole gate: the criterion it
  replaces — `curl -sI | grep -i content-type` — is in T3.6's own task file as an example of a
  check that cannot fail.

**A new assertion mechanism gets its own tests before it is trusted.** `mismatched_headers` is
pure and has nine, including the one that matters: a prefix does not match, so
`application/vnd.android.package` is rejected against `application/vnd.android.package-archive`.
This repository has shipped four criteria that could not fail; that is the cheapest place to
stop the fifth.

### T7.2's real answer was a property of adb, not of Docker

The task asked whether `adb pair` works from inside the build container. The useful answer is
that it should not be asked to: for the container to use the host's adb server, that server has
to accept a connection from the bridge, and **adb cannot listen on one interface** —
`adb -a -L tcp:172.17.0.1:5037 nodaemon server` exits with `listening on specified hostname
currently unsupported`. The only server a container can reach is `adb -a` on `0.0.0.0:5037`:
unauthenticated control of the phone for everyone on the LAN. The route works. It is not worth
it on a desk whose entire security model is "the network is the boundary".

On the way there, a bug that was already in the repository: `make connected` passes
`-PadbHost=host.docker.internal`, and **that name does not resolve on Docker Engine** — it is a
Docker Desktop invention. `docker/compose.yml` maps it now. TT.7 would have hit it as "Gradle
cannot find a device", which names neither the cause nor the file.

### Found on `main`, not fixed here, and it needs a row

**`python scripts/after_update.py --self-test` exits 1 on this Linux box**, two cases red:

```
FAIL  python_for: pythonw.exe -> python.exe, same directory
FAIL  python_for: case does not matter on Windows
```

It is red on `main` too, so this wave did not cause it. `python_for` uses `Path`, which is
`PosixPath` here, so `Path(r"C:\Python313\pythonw.exe").name` is the entire string and the
function returns it unchanged — correct behaviour on Windows, untestable on Linux. The fix is
`PureWindowsPath` for the Windows branch, which is what `verify_login_scope.py` already learned
in T3.8: *"`check_macos_agent` tested `"/Library/LaunchAgents/" in str(path)` and a
`WindowsPath` stringifies with backslashes, so the macOS row silently failed on the primary
platform."* Same defect, mirrored.

**The shape is the finding, not the two cases.** Wave 20 discovered that the server suite had
been red on Windows since wave 18 because both waves were judged on Linux. Its own script is now
red on Linux because it was judged on Windows. Nothing in `make check` runs `--self-test`, so
neither direction is caught by the loop — it is caught by whoever happens to run the other OS.
Wiring `--self-test` into `make check` is one line and is the actual fix; **it needs a task
file**, and this section is not one.

### What the next wave inherits that is only true on this desk

- **The phone is not on adb.** It answered `unauthorized` over USB at the start of this wave and
  had dropped off entirely by the end of it. T7.2, T2.4, TT.7 and TT.8 all need it back, and the
  first step is the RSA prompt on the device, which nobody can tap from here.
- **The panel's own server was stopped and started twice** during this wave, because
  `probe.py --serve` refuses to probe a listener it did not start and T3.9's user unit owns
  8777 on this box. That is the tool working. It also means the panel slept and woke twice, and
  a restart is a logout as far as the phone is concerned.
- **`extra_hosts` is verified on Docker Engine and unverified on Docker Desktop**, where the
  name already exists and the line should be inert. "Should be" is the honest word.
- **The container's adb was seen attaching to a host server, with no device attached.** The
  connection is what was in question and the connection is proved; an actual device over that
  socket is not.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants
  it. Carried from wave 19 through 21, still not done.

## Resuming after 2026-09-23 (wave 21)

Wave 21 is **T0.6**, on `wave/21-the-two-agent-setup`, PR #27. It is the oldest row in the table
and the
one that had carried the `start here` marker since the bootstrap — the two-agent setup that
arrived whole in PR #1, outside the task system it was meant to live in.

**It was numbered 20 for most of its life.** A second session was working in this same checkout
at the same time and merged its own wave 20 (PR #25, `after_update.py`) while this branch was
open; the collision surfaced at the merge, not before. Both sections are below, newest first.
Renaming the remote branch to match then **closed PR #26** — GitHub does not retarget a pull
request whose head branch is renamed out from under it — so the wave's PR is #27.

**Next: T3.6 + T7.2** — serve the APK at `/app`, and wireless adb from the container. They pair:
both are about getting a build onto the phone without a cable, and T7.2 is allowed to fall back
to host platform-tools. After that the backlog is TT.4+TT.9, TT.7+TT.8, T8.1, T8.2, T7.4+T7.5,
T7.6+T7.7+T7.8, and T7.3 last.

Four rows stay blocked on hardware or on a session that has not happened: **T2.4** and
**T3.10** (no Mac), **T3.9**'s human half (a second device and a graphical logout), and
**T3.8**'s Windows half.

### One thing is open outside the task system

The panel **did not come up by itself when the Windows box was switched on**, reported from the
chair on 2026-09-23, while the CachyOS carrier from wave 18 does it every login. Nothing was
diagnosed — there is no Windows machine here to ask. `WINDOWS-NEXT-SESSION.md` at the repository
root is the triage to run on that side, in order, and it is **temporary**: delete it once the
cause is known. Its first hypothesis is the one the repo already documents — T3.12 moved config
to TOML on 2026-09-20, one day *after* the Scheduled Task was registered with an absolute
`--config ...\server\config.json` baked into its action, and deleting that file makes the
server exit 1 at every logon under `pythonw`, silently.

### Measure the harness, do not read about it

Two of this wave's five acceptance lines were wrong as written, and both were settled in about a
minute each by running the thing instead of trusting its documentation:

- **`forbid_read` does not accept globs.** A decoy `a.keystore` in a scratch fixture printed
  under `forbid_read = ["*.keystore"]` and returned `Permission denied` under the literal name.
  The keystore had been readable by the local agent and not by Claude the whole time.
- **`--permission-mode read-only` does not exist**, and `plan` — the mode that means it —
  refuses to run headless. The task file had been written from the shape of the other harness.

The general rule is the one wave 19 paid for in a different key: when a claim is about a tool's
own behaviour, a fixture answers it faster than the docs do, and correctly.

### What the next wave inherits that is only true on this desk

- **`make check` now has four layers, not three**: `lint-permissions` runs
  `scripts/check_permission_parity.py`. A permission added to one file and not the other is a
  failing build from here on, which is the point, but it also means a PR that touches either
  file needs the other one in the same commit. **It cannot see a rule missing from both files** —
  that is how this wave shipped a `make lint-permissions` target neither agent was allowed to
  run, with the check green.
- **A deliberate asymmetry is declared as `# parity: intentional (allow)` / `(deny)` /
  `(allow, deny)`**, naming the list. A declaration without a list is now an error rather than a
  blanket, because a rule can be asymmetric in both lists for opposite reasons.
- **The parity checker compares families, not spellings.** `Bash(adb devices)` and
  `Bash(adb devices:*)` are equal to it. That is deliberate — the question is what a command can
  do, not how a harness punctuates — but it means a genuinely narrower rule on one side reads as
  in step. If that ever matters, it is a change to `normalise()`, with a reason.
- **Ollama has to be up for the last acceptance line**, and `ollama ps` must read `100% GPU`;
  a partial offload is roughly ninefold slower. The model was resident at 8.1 GB / 131072
  context when this wave ran.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants
  it. Carried from wave 19, still not done.
- **The 34px moon and the 24px rain icon are still held up by `check_layout.py` alone**, and the
  pulse has still never been seen firing on the device. Both carried from wave 19 unchanged.
## Resuming after 2026-09-22 (wave 20)

Wave 20 was not planned by wave 19. It came from the chair, and it started as a question — *do I
have to update the server that starts with Windows?* — which turned out to have a more
interesting answer than "no".

**Next**: wave 19's recommendation still stands and is now the first thing due — it is in the
wave 19 section below, unchanged by this one. Two things this wave surfaced belong near the top
of whatever comes next:

- **T3.10 (macOS) is still `blocked` and is now referenced by name in a shipped script.**
  `after_update.py` reports `unknown` on Darwin and `docs/UPDATING.md` says what joins it. That
  is honest today and becomes stale the moment a Mac exists.
- **`config.json` is still what this desk runs.** The Scheduled Task bakes `--config
  …\server\config.json`; migrating means re-running `install_task.ps1`, not copying a file.
  `after_update.py` surfaces the server's own notice on every run, so it is no longer a thing
  only the startup log knew.

### A pull is not a deploy, and nothing in the repo knew it

The phone had a fresh APK with two new cards and both were empty. Everything anybody would check
was innocent: `/ping` answered, the panel was lit, the config was valid, the tests were green,
the APK was current. The Scheduled Task had started at 00:31:18; the pull rewrote `server.py` at
00:32.

Every liveness check this repo owns asks *does it answer*. `probe.py` asks it, `/ping` asks it,
`verify_login_scope.py` asks why it answers. **None of them can tell yesterday's server from
today's**, and a launcher whose action points into the checkout makes that gap permanent rather
than occasional. The fix is one check — compare the live payload against the key set the tree's
own code produces — and it is worth more than the rest of the script.

### The restart was the dangerous part, not the diagnosis

Stopping and starting the Scheduled Task back to back took the server down completely:
`WinError 10048`, and the process that survived was the one that had just been asked to die.
That is `allow_reuse_address = False` working exactly as designed on Windows — a second server
must fail loudly rather than quietly serve half the requests — and it means the obvious two
cmdlets are the wrong way to restart this. The socket has to be watched in between. The
installer already knew a version of this (it sleeps 2 seconds after its own stop); nothing had
written it down where a human restarting by hand would find it.

### The wave found a red suite that two waves had shipped over

`make check` was red on the Windows host, eight failures, since wave 18. Both waves were judged
on Linux, where it passes. It was not the escaping it appeared to be — it is Git Bash eating a
backslash out of `sed`'s `-e` argument — but the finding underneath is about the loop, not about
`sed`: **nothing in the harness runs the server suite on the primary host.** `after_update.py`
now does, as a side effect of its own job, which is the only reason this was caught at all.

Three reproductions were wrong before the real cause landed, each mangled by a different quoting
layer — including the agent's own shell, which collapses a doubled backslash in the commands written to
diagnose backslash handling. Reading bytes out of the file was the only thing that settled it,
and that is the lesson worth keeping: when the bug is about escaping, every layer between you
and the evidence is a suspect.

### What the next wave inherits that is only true on this desk

- **The unit-rendering test is skipped here**, so `install_user_unit.sh`'s escaping is unverified
  on this machine. It is verified on the CachyOS box, which is also the only place the installer
  runs.
- **`after_update.py`'s restart path is exercised on Windows only.** The Linux branch
  (`systemctl --user restart`) is written and has not been run; the macOS branch does not exist.
- **The APK proxy is cold.** `.after-update-state.json` records the first clean run, so the first
  report said `unknown` rather than naming files. It only starts answering from the second run.
- **The panel was confirmed by eye, on the device**, after the restart: the chance of rain and
  the moon both render. `/weather` was asserted by command; the two cards were not.

## Resuming after 2026-09-22 (wave 19)

Wave 19 is **T6.13 + T6.14 + T6.15**, on `wave/19-the-moon-the-jump-and-the-loop`. All three came
from the chair, in Portuguese, with the panel lit — the session ran from the evening of the 21st
into the small hours of the 22nd.

**Next: T0.6** — the two-agent setup, the oldest row in the table that is not `done` and the one
still carrying the `start here` marker from the bootstrap. Everything scheduled in phase 6 is
finished; T6.9 through T6.15 all arrived from the chair instead, so the backlog is where it was.
Read the `Prereqs:` lines rather than the phase order.

Two rows are blocked on hardware rather than on work and stay that way until it is here:
**T3.9**'s human half (the SSH round trip needs a second device, the login/lock/logout sequence
needs a graphical logout) and **T3.8**'s Windows half (no PowerShell on this machine).

### Read the switch before the mechanism

The wave's expensive hour is worth more than its code. A live report — "câmbio e cripto pararam
de girar" — was chased through four hypotheses, three of them built and installed on the device,
before the cause turned out to be `data-night=on`: every measurement had been taken after 22:00,
inside the panel's own night window, where `css/style.css` removed every CSS animation.

That one rule explains every observation, including the two that looked most like engine bugs —
an inline `animation` failed because `!important` beats it, and the Web Animations API worked
because the cascade cannot reach a WAAPI animation. **A whole task file and implementation were
written on the false premise and discarded unmerged.**

The lesson is not "measure more". A great deal was measured, carefully, and most of it was the
wrong thing. It is that this panel has three documented rules that can stop an animation — the
blackout, the night profile, `prefers-reduced-motion` — and reading those three costs one probe.
**Check what is switched off before instrumenting how it works.** The attribute had even been
seen: a Firefox probe printed `night: true` mid-session and the line was walked past.

### Two decisions were the owner's and were put to them as such

Both of tonight's complaints turned out to be the panel doing what it was written to do, decided
for a panel this is not:

- **The jump** is the anti-burn-in shift, 4px every 4 minutes, instantaneous by design. The
  table's comment argued for big steps as "the least relief per move"; that is true of one move
  and the wrong quantity. The one-pixel path was chosen from the chair with the trade-off stated.
- **The night stillness** was a promise about a dark bedroom, and invariant 3 means the room has
  somebody awake at a logged-in machine in it. Removed, with the cost recorded where the rule was.

Neither was changed without asking, and `docs/adr/0008` should be re-read before either is
revisited — nobody here can measure AMOLED wear, and the burn-in argument is an argument.

### What the next wave inherits that is only true on this desk

- **The fallback and the warm-up are both proven on the device**, which they were not when this
  section was first drafted. Because the moon fetch is off the request path, the first
  `/weather` after a restart answers `source: "mean"` and the next answers `usno`: 11.0 days and
  85% from the USNO's lunation against 10.29 and 79% from the arithmetic, on the same instant.
  That difference is the reason the API is the plan.
- **The 34px moon and the 24px rain icon are held up by `check_layout.py` alone.** Between them
  they spend most of the card's 6.6px of slack, and the stress pass on all three variants is the
  only thing between them and an overflow in a language nobody looked at. Both were raised from
  the chair until the check refused.
- `server/config.json` is still mode 0644 and holds the brapi token. One `chmod 600`; T7.3 wants it.
- The moon's southern-hemisphere convention is a constant. Every phase mirrors north of the equator.
- **The pulse has never been seen firing on the device.** It is 280ms and the night rule had
  suppressed it entirely until tonight, so it has had no chance to be watched.

## Resuming after 2026-09-21 (wave 18)

Wave 18 is **T6.12 + T3.9**, on `wave/18-two-cards-and-linux-autostart`, PR #23. T6.12 came
from the chair; T3.9 was the backlog's next row and the last platform missing its carrier for
invariant 2.

**Next: T6.13**, which is already `wip` — its step 1 is committed and green, and steps 2 to 5
are open. Read the task file: it was written from the chair on the same evening and its own
cross-check has been corrected once already.

### The wave was interrupted, and the review did not survive it

The PC locked up after the first review had been run and its fixes applied, but before the
merge. The session went with it. What was left in the repository was a branch, three commits,
and an uncommitted working tree — and **no record of what had produced the working tree.** The
fixes were identifiable as review output only because the comments they add say so.

They were reconstructed by reading the diff, which is a guess in a report's clothes, so the
branch was reviewed again from scratch. That was the right call and not a formality: **four of
the second review's five findings were in code the first review had written**, including a
`sed_escape` that emitted one backslash too many and so spliced the placeholder's own text into
the path it was escaping — a guard that produced exactly the corruption it was added to prevent,
under a comment describing that corruption correctly.

The lesson is cheap to act on and is now in the harness note: **write the note as the review
lands, not after the merge.** The note is the only artefact of a review that outlives the
session, and a session is not durable.

### Two measurements outlived the thing they measured, again

Findings 3 and 4 of the second review were a status row claiming 12px of slack that `theme.css`
had already been corrected to 6.6, and a row-height argument computed against the 48px
temperature T6.12 replaced with 44. Neither failed anything. Both were confident.

This is wave 17's headline arriving for the second wave running, and it is now the thing to
watch for rather than a coincidence: **a number written into a comment or a status row is a
claim with no test behind it.** Where one matters, the cheap fix is the one T6.13 is already
using — check it against a source outside this repository and say in the file where it came
from.

### What the next wave inherits that is only true on this desk

- `server/config.json` is still mode 0644 and holds the brapi token; the server warns on every
  start. One `chmod 600`, and T7.3 will want it done.
- The running server on this desk has **not** been restarted onto the new provider code, so
  `is_day` has not been seen arriving from the real upstream. T6.13's manual check needs that
  restart and a clear night.
- T3.9's human half is still open — the SSH round trip needs a second device, the login/lock/
  logout sequence needs a graphical logout. The unit itself is installed, enabled and correctly
  scoped on this machine.
- The hostile-path substitution is tested but not lived: nobody has installed from a checkout
  whose path contains `&`, `|`, `\` or a space.

## Resuming after 2026-09-21 (wave 17)

Wave 17 is **T6.9 + T6.10 + T6.11**, on `wave/17-scroll-icons-and-language`, and none of the
three came from the backlog: all three were asked for from the chair, in Portuguese, while the
panel was on. That is worth noting because it is the first wave driven by somebody using the
thing rather than by the plan.

**Next: T3.9** (the systemd user unit), unchanged — wave 16 pulled TT.10 forward so T3.9's
parsers land already tested, and what it still needs that nothing here provides is a second
device for the SSH round trip.

### The scroll goes round, and the seam is the whole difficulty

T6.6 gave an overflowing card a walk down to its hidden rows and back. Two things about that
were wrong once it was living on a desk: four seconds a row was chosen against a movement with
*ends*, and a movement that never ends is one the eye keeps returning to; and half its life was
spent showing rows it had just shown.

The loop is the oldest trick there is — the list drawn twice, the box moved by exactly one copy
— and the one part that can be wrong by a pixel and look right in every frame but two is the
distance. **It is measured off the clone, not computed from `scrollHeight`.** Rows carry a
border between them and none after the last, so a copy sitting inside a pair is one border
taller than a copy on its own, and that pixel is a jolt every couple of minutes: the exact
motion T6.6's notes ask this panel never to make, arriving by the back door. `check_scroll.py`
asserts the pitch *exactly* rather than within a tolerance — a tolerance there is a tolerance
on the jolt — and it was mutation-tested from both sides.

`plain` keeps a different number from `neon`, 24 against 16, because its rows are two lines
tall. The quarter is the ratio, not the constant.

### The battery icon draws its own charge, which is more than was asked for

The ask was to replace `BAT` with a picture. A static outline beside a two-digit number is a
label; a filled one is read *before* the number is, which is the same trade the sparkline makes
beside a price. Dropping the `<rect>` in `renderBatteryIcon` puts it back to a plain outline.

The bar goes to the body's **inner** edge and not to the path: a 1.6-unit stroke sits half
outside the line it is drawn on, so a bar drawn to the path's own coordinates disappears under
its own outline and reads as one solid lozenge at every level above about 80%.

`unplugged` is still a word, deliberately. There is no picture for "this phone is now running
its own battery down" that a stranger reads the way they read a battery outline, and it is the
one thing in that corner that matters (ADR 0014).

### The language is config, and the fallback is pt-BR

Everything a person reads comes from a table in `format.js`, and `language` rides `/quotes`
beside `theme` and `night` — so a panel in another country is a restart of the server and never
a rebuild (ADR 0013). `DataPayload.merge` copies it, with a test, because that copy is exactly
what T6.4 forgot and nothing else in any layer would have noticed.

Two decisions that could each have gone the other way:

- **The fallback is pt-BR, not English.** The same call `host.useTheme` makes about an unknown
  theme name: a typo in a file on the PC must cost nothing anybody can see, rather than
  switching the whole panel to a language its owner did not ask for.
- **The device's own locale is not consulted.** A phone in a stand running its system in one
  language is not evidence about who is looking at the panel, and there would be no way to ask
  for the other one. `toLocaleDateString(undefined, …)` was doing exactly that and is why the
  date was English under Portuguese words.

English stays everywhere else — code, comments, docs, commits — and that is not an
inconsistency. Those are read by whoever works on this; the fifteen strings on the glass are
read by whoever owns it.

`DEFASADO`, not `DESATUALIZADO`: the badge shares its strip with the weather card's title and
neither word is fixed any more. The badge also came down from 20px to 17, because the title is
read every minute of every day and the badge is on screen for minutes a month. The constraint
left behind is real and a third language has to be checked against it — `check_layout.py`
takes `--lang` now.

### The harness could not see either collision, and that is the bigger finding

`measure.js` compares *ink* rather than boxes, because two sections are allowed to share a
rectangle. Two whole categories of ink were invisible to it, and T6.11 walked into both at
once:

- **A `::before` has no DOM node**, so `querySelectorAll('*')` had never been shown a card
  title. It measures them now with a probe span carrying the pseudo's computed font — the only
  way to get a width for text with no element. Firefox computes the `font` shorthand to the
  empty string on a pseudo, so the probe has to copy the longhands; with the shorthand it
  measured the text in the document's default face and answered quietly wrong.
- **The ink walk started at a section's *descendants*.** A section whose text sits directly on
  the section element — `#clock`, `#date` and `#stale-badge`, three of the eight — contributed
  no ink at all. The overlap check has therefore never been able to see the clock, the date or
  the badge collide with anything, in the file whose entire purpose is to catch exactly that.

Both were found by trying a thirteen-letter Portuguese word for STALE, watching it land
squarely on `TEMPO`, and being told the pass was clean. Fixing the second is what made the
first one's measurement mean anything — and with both fixed, even `DEFASADO` at 20px was
reported as a 4x18px overlap.

### Verified

`make check`; the five browser checks across **both themes and both languages** (sixteen
combinations for the four that take `--theme`, plus `check_pulse`); and the panel itself on the
phone, in pt-BR, with both icons and the release APK installed.

### What is still only true on this desk

- **The loop has not been watched for a full pass on the device.** The seam is asserted to the
  pixel by `check_scroll.py` in Firefox, and whether sixteen seconds a row reads as scenery
  rather than as motion from a chair is the task's manual check.
- **The server on this desk is running again**, started by hand for the device check and left
  up. Stop it **by PID**, found through `ss -ltnp 'sport = :8777'`, never
  `pkill -f "server/server.py"`.
- **Only two languages ship**, and the badge-versus-title constraint is not enforced anywhere
  except by running `check_layout.py --lang` for each one. A third language that nobody
  measures will overlap silently — which is now at least *possible* to catch, and was not
  before this wave.

## Resuming after 2026-09-21 (wave 16)

Wave 16 is **T6.4 + TT.10**, on `wave/16-night-profile-and-login-scope-tests`. The panel dims
between 22:00 and 07:00 — backlight to `0.15f`, glow halved, nothing moving — and the three
platforms' login-scope parsers are now tested from recorded output on whatever machine you
happen to be on. **Phase 6 is finished.**

**Next: T3.9** (the systemd user unit). TT.10 was pulled forward out of that wave on purpose,
so T3.9's parsers land already tested — and TT.10's assertion that the unit must be outside
`default.target`'s closure is exactly the property T3.9 has to build. What T3.9 still needs
that nothing here provides is a second device: its behavioural half is an SSH round trip and a
graphical logout, which is the same shape of blocked half T3.8 carries.

### The night profile is decided twice, in two languages, and that is the design

`isNight` in `js/format.js` decides what the panel looks like; `NightWindow.java` decides what
the backlight does. The mechanisms do not meet — one is a CSS custom property, the other is
`WindowManager.LayoutParams.screenBrightness`, which no page can reach — and pushing a boolean
from Java into the page would have made the browser, where there is no Java and `mock.js` is
the whole feed, the one place the profile could not be developed. Both read the same two
bounds out of the same payload against the same device clock, so they can disagree only for
the seconds between a minute boundary and the next refresh.

The server sends the two strings and never a boolean, and that is the other half of the same
decision: **the panel is what sits on the desk**, so a phone carried to another timezone dims
at the local hour. A server that decided would answer with its own clock and the panel would
dim an hour late for ever, with nothing to explain it.

### The device acceptance found a defect nothing else could

`DataPayload.merge` rebuilds the payload key by key rather than patching it, so a key nobody
names there never reaches the phone. The first build had a correct server, a correct page, a
correct predicate on both sides — and no `night` in the merge. The panel stayed bright all
evening, with nothing in logcat, no exception, and every other check green.

That is the second time this project has shipped a feature whose wiring was missing in exactly
one line, and both times the evidence came from the device. There is a JVM test for the copy
now, and a second one for it surviving `withBattery`, which is a separate rebuild.

### The acceptance in the task file could never have passed

`adb logcat -c && sleep 90 && adb logcat -d -s DeskPanel | grep -q 'night=on'` waits for a line
a correct app is right not to write. Every marker in this app fires on a transition — `state=`,
`screen=`, `dormant=` — and ninety seconds of an unchanging panel produce nothing. An
implementation that *did* pass it would be one logging the marker every refresh, which is the
contract broken.

`e2e/check_night_marker.py` drives the only input a test can reach, the window in the PC's
config, and asks three questions: a steady panel logs nothing across two refreshes (which is
what the original acceptance was reaching for, and the assertion that fails an app logging the
marker per refresh), a window containing now turns the profile on, and the window *ending*
turns it off. It runs the server itself under a temporary config, because changing that config
means a restart and restarting somebody's running server is not a script's to do.

**Driving the edges took three attempts, and the failures are the interesting part.** The
obvious way is to restart the server into a new config — and a restart is a gap in the server's
answers, so a gap the probe ladder notices is a logout as far as the phone is concerned. The
falling edge passed for the wrong reason, visibly:

```
19:36:22 night=on
19:36:24 state=offline
19:36:24 screen=sleep
19:36:24 night=off      <- not the window. The PC leaving.
```

The second attempt drove the falling edge off the clock — a short window that expires while the
server sits there answering — and left the rising one behind a restart. That one then had to
reconnect a possibly-dozing phone inside a window with minutes left to live, and passed with
about seventy seconds of margin, which is not a pass anybody should rely on.

The third serves the window **once, before it opens**, from a server that never moves. The
clock walks into it and back out of it, which is what happens at 22:00 and 07:00 anyway; there
is no blip to have and no reconnect to race. Both edges are guarded regardless — a
`state=offline` before either marker fails the run, checked by position in the buffer rather
than by comparing the timestamps logcat prints, which carry no year and sort backwards across
New Year.

**The quiet window needed two refreshes before it could mean anything**, and that too was the
feature working rather than a flake: the app keeps the window across an offline stretch, so a
panel left in the night profile by a previous run comes back still in it and corrects itself on
the first day payload. A `night=off` four milliseconds after a `data=ok`, reading as a marker
that fires per refresh.

### What the review found, and all four were real

- **`e2e/check_night_marker.py` named `server/config.json` directly** instead of going through
  `config_search_paths`, which exists for this and prefers `config.toml`. On a machine set up
  the documented way (T3.12) the acceptance would have died with a `ConfigError` traceback
  rather than the clean `FAIL:` line every other path in that file produces.
- **`check_night.py` hard-failed a theme that answers an overflow without motion**, which the
  theme contract explicitly allows and `check_scroll.py` already guards for — while
  `docs/TESTING.md`, edited in this same wave, requires the night check of *every* theme. Both
  shipped themes animate, so it would have bitten the next one.
- **`NightWindow` accepted `22.5` and truncated it to 22:00** where `isNight` rejects it, so a
  fractional bound in a TOML config would have dimmed the backlight behind a page that kept its
  glow — each half correct on its own, which is the most confusing way this could fail. It is
  the only input where the two readers could have disagreed, and the javadoc directly above it
  claimed the parity was the point.
- **A comment said "three custom properties" where the block redefines two**, the third being
  the alarm's, which the same block goes on to say must never be dimmed. `docs/THEMING.md`
  repeated the claim. In a repo where comments are the design record, that is a licence to do
  the one thing the design forbids.


### What is still only true on this desk

- **The 0.15f backlight has not been judged by eye in a dark room.** The marker says the
  profile engaged and the browser check says the glow dropped; whether a panel at 0.15 is
  legible at 50cm at 03:00, and whether halved glow reads as *dim* rather than as *broken*, is
  the task file's manual check and it is outstanding.
- **The scroll does not run at night**, so a card with hidden rows keeps them until 07:00. That
  is the intended trade — the panel at that hour is a clock first — and nobody has lived with
  it yet.
- **The server on this desk is still started by hand** (T3.9 is still `todo`), and
  `check_night_marker.py` refuses to run while something holds 8777. Stop it **by PID**, found
  through `ss -ltnp 'sport = :8777'`, never `pkill -f "server/server.py"`.
- **The phone runs the release build.** T6.4 needed the device, and a debug APK cannot be
  installed over a release one; `docker compose -f docker/compose.yml run --rm build
  ./gradlew assembleRelease` then `adb install -r` is what was run.
- `scripts/check_status.py` exits 1 on two rows that predate this wave — T9.1 and T9.2 name
  ADRs 0015 and 0016, which are not written yet. Not a regression from here.

## Resuming after 2026-09-20 (wave 15)

Wave 15 is T6.2 alone, on `wave/15-glow-and-burn-in`. **The panel moves.** Every four minutes it
sits a few pixels somewhere else, so that one unchanging layout on an AMOLED does not etch
itself into the glass — and four things glow where nothing but the clock did, and a value that
changed says so for 280ms.

**Next: T6.4** (night profile), and it is the last of phase 6. Its web half is smaller than its
task file implies — `isNight` has been in `format.js` and under test since T5.x — and its
`night: {start, end}` is already in the payload and in `mock.js`. What it still needs is the
native half (`screenBrightness`, the `night=on` marker) and a phone, which makes it the first
task since T5.5 to need the device.

### The one decision, and it contradicts the task file

**The burn-in shift is core.** T6.2's `Files:` line said a theme, on the reasoning that a layout
shift is presentation. The competing rule is newer and won: T6.7 put the blackout in
`css/style.css` because it is the page's half of a promise about *hardware*, and wave 14 put the
animation pause beside it for the same reason. A theme that forgot to move would look perfectly
fine and quietly etch the display, which is that failure in that shape.

So `offsetFor(now)` decides in `format.js` (pure, tested), `js/host.js` writes it into
`--burn-in-x/--burn-in-y` on every tick, and one rule translates `body > *`. A theme owes it
three things and all three are "do not"s (`docs/THEMING.md`). The task file carries the
amendment and the reasoning.

### Two constraints on the cycle that nobody asked for and both are load-bearing

- **Every offset is up and left, never down or right.** A transform past the bottom or right
  edge becomes the *document's* scrollable overflow. The panel is exactly one screen and
  `check_layout.py`'s first question is "does the page scroll" — and a page that can scroll is a
  page with somewhere to hide a row, which is the fault T6.6 exists to fix, arriving by the back
  door.
- **The step counts from the epoch, not from midnight.** Counting from midnight was the first
  cut, it passed every other test, and it fails the task file's own closing note in one
  sentence: the PC is on for roughly the same hours every day, so every offset would land under
  the same glyphs at the same hour for ever. That is a rota, not a mitigation. From the epoch a
  day is 360 steps against a cycle of seven, 360 mod 7 is 3, and the phase advances three
  positions a night. **The test named for it is what caught it**, which is the first time in this
  project a test has failed on a property nobody had implemented yet.

### The harness was about to become time-dependent, which is worse than untested

A panel that moves has seven positions, and `check_layout.py` measured whatever the wall clock
had put on screen. A card that escapes the viewport only at `(-4,-3)` would have been a check
that fails on a Tuesday — the most expensive kind of failure this repo has, because the next run
passes.

It now walks the whole cycle and measures at each position, and asserts two things one
measurement cannot: that core's offset **reaches the glass** (delete the rule in
`css/style.css` and the sweep still runs seven times, still passes, and has measured one
position seven times), and that the panel **moves at all**. Both were mutation-tested.

Making the sweep work needed the page's clock pinned, and that fixed something older by
accident: the stress pass rendered **today's** pt-BR date, so "the widest case the panel can be
asked to show" was only the widest case on the days it happened to be. It is pinned to
`segunda-feira, 23 de fevereiro de 2026` now — the longest such date of the year, at 38
characters, and it still fits the sidebar in two lines. Screenshots are comparable between runs
again as well.

`check_pulse.py` is the fourth browser check and it is the only one that is about a *theme*
rather than about the panel. It exists for one failure that is invisible on this desk: `onData`
replaces every row every minute whether or not a number moved, so a pulse keyed on the payload
arriving looks perfect in a browser — `mock.js` jitters every price every three seconds — and
on the device, with an upstream down and the server serving last-good values, it flashes the
whole panel once a minute while STALE sits in the corner saying nothing has moved.

### Two cross-realm traps, one in the page and one in the harness

Both cost time and both are the same mistake in two places, so they are worth naming together:
**`Date` is not one type, it is one type per realm.**

- `offsetFor` guarded its argument with `instanceof Date`. A Date built anywhere else — an
  iframe, a harness driving the page from outside — is not an instance of *this* realm's Date,
  so the guard answered the origin for every clock the sweep handed it: seven positions, all
  `(0,0)`, and a burn-in feature that reported as working perfectly while doing nothing. It is
  duck-typed now. In production the Date comes from `js/app.js` and the bug could never fire;
  the point is that it failed **silently**, and the sweep's own "the panel never moves"
  assertion is the only thing that caught it.
- Marionette executes in its own sandbox with its own globals, so `new Date()` inside an
  injected script is the *harness's* clock however carefully the page's one has been pinned.
  `check_layout.py` and `stress.js` both say `new window.Date()` now.

### The review found seven, and the first one broke the feature's own promise

**A wake from the blackout pulsed every number on the panel.** The pulse compares what it is
about to draw against what the panel is showing, read out of the markup — and the blackout
*hides* `body`, it does not empty it (T6.7: coming back is a repaint, not a relayout). So at
nine in the morning, with the PC just switched on, every row from last night was still mounted,
every price in it differed, and all of them flashed at once. The comment above the code named
that exact outcome as the thing the design avoided. It guarded a row that was *absent* — a new
ticker, a theme switch — and nothing else.

The fix is the first change to the theme contract since T6.7 created it: `render` takes a third
argument, and `context.resumed` is true on the first render after the panel has been dark.
Core knows which render that is and a theme cannot work it out, which is exactly the shape of
thing the boundary is for. `plain` ignores it; `docs/THEMING.md` documents it, and generalises
it past the pulse — **what is in your markup was not necessarily seen.** `check_pulse.py` grew
a fourth question and it was mutation-tested from both sides.

**A test passed only in some of the world's timezones.** `offsetFor holds one position for the
whole of a step` anchored its loop at local midnight, and steps are counted from the epoch — so
local midnight is a step boundary only in a zone whose offset divides by four minutes.
`TZ=Asia/Kolkata node --test` was 63 of 64. It anchors to a computed boundary now, and the
suite is run under three zones before this section gets written.

**The offsets table did not have the property its comment claimed.** Seven entries cannot use
five values once each; and the y column summed to −13 rather than −14, so the ink sat very
slightly low in the band. The table is corrected and, more to the point, the claim is now a
test: every value in the band appears in each axis, and each axis has a mean of exactly −2.
That is the fourth claim-without-a-check this repo has caught, and the first one caught in the
same wave that wrote it.

### And four smaller ones, all invisible on screen

- **The shift ran outside any try**, one line above the theme's guarded tick, and it calls a
  global out of `format.js`. That made the panel's *clock* — the one thing it owes
  MainActivity (ADR 0009) — depend on that file having loaded. It has its own try now, which
  keeps both halves of what the placement was for.
- `check_layout.py` read the pinned instant out of the page once per position rather than once
  per pass: twenty-one round trips to compute an addition.
- `document.body.firstElementChild.getBoundingClientRect()` throws on a theme that rendered
  nothing, so the harness would have **crashed where it should have reported**. "The harness
  crashed" and "the panel is empty" are not the same finding, and an empty page is the failure
  this directory already has three guards against.
- `check_scroll.py` picks the first animating element in a card, and until this wave there was
  only ever one. A pulsing value is a second. `[0]` is still right — the box that moves a card's
  rows contains them, and an ancestor precedes its descendants — but that is now a fact worth
  writing down rather than a coincidence the next person re-derives.

Plus three of the review's own: the `will-change` comment said T6.6 had *refused* it when T6.6
had in fact **scoped** it under `[data-scroll]` — in a repo where comments are the design
record, that sends the next reader looking for a decision made the other way; `check_pulse.py`
hard-coded `plain` as the theme it switches away from to empty the panel, so `--theme plain`
silently stopped asking its first question at all; and `docs/TESTING.md` said all four browser
checks pin the clock and sweep the burn-in cycle, which is true of one of them.

`docs/TESTING.md` gained the browser harness at the same time, which it had never mentioned:
four checks since T6.1 and no entry in the file that says how this project is tested.

### What is still only true on this desk

- **Nothing in this wave has been seen on the phone.** It is web-only, like wave 14, and it was
  verified the way wave 14 was: the four browser checks, both themes. What that cannot answer is
  whether a 10px halo reads as light or as a smudge at 50cm on a real AMOLED with Roboto
  Condensed — the host falls back to a wider face, and the harness measures geometry. The
  task file's manual check says so and it is outstanding.
- **The server on this desk is still up** and still started by hand (T3.9 is still `todo`). Stop
  it **by PID**, found through `ss -ltnp 'sport = :8777'`, never `pkill -f "server/server.py"`.
- **The pulse fires every three seconds in a browser** and once a minute on the device. That is
  `mock.js` jittering every price, not the feature being loud — and it is exactly why the
  browser is the wrong place to judge whether 280ms is right.

## Resuming after 2026-09-20 (wave 14)

Wave 14 is T6.6 and T6.8, on `wave/14-overflow-and-weather`. Two tasks rather than one because
after T6.7 they are the same shape of work — both are pure functions in `format.js` plus a
theme spending them, both run entirely on this machine, and both are measured by the same
harness. **The cards spend the space they have.**

- **T6.6.** A card that holds more rows than it can show now walks slowly through them, four
  seconds a row in neon and six in plain, holding at each end. Before it, the sixth ticker was
  not truncated and not marked — it was absent, and nothing on the panel said so.
- **T6.8.** The weather card was the tallest on the panel and held one 24px line. It is now a
  hierarchy, and the range it renders can be read below zero.

**Next: T6.2** (glow, micro-animations, burn-in shift), then T6.4 (night profile). Phase 6 has
nothing else left. Read T6.2's header before starting it: its `Files:` line still says
`web/css/style.css` and `web/js/app.js`, and both of those are wrong in the way T6.6's were —
glow and a layout shift are presentation, so they land in `web/themes/`, and only `offsetFor`
belongs in `format.js`. **It also has to be reconciled with this wave**: T6.6's note asks that
the burn-in shift and the scroll not fight, and there are now two independent motions available
on one card. T6.4 is half-blocked on the phone — the `night=on` logcat marker — but its
`isNight` predicate has been in `format.js` and under test since T5.x, so the web half is
smaller than the task file implies.

### Where the difficulty actually was, and it was not the animation

T6.6 named it correctly: `window.onData` rebuilds each list wholesale every 60 seconds, so a
CSS animation resets before it ever reaches the rows it exists to reveal. The task offered two
answers — update the rows in place when the symbol set has not changed, or carry the offset
across the rebuild — and **neither was needed.** A CSS animation belongs to an element, and
replacing that element's children does not disturb it. So the rows went into a `.scroller` that
`mount()` builds once and `render()` only refills, and the rebuild became a non-event.

That leaves one way to break it, and it is the reason `scrollPlan` is pure and tested for
determinism: the theme rewrites `--scroll-seconds` and `--scroll-distance` on every render, and
an animation whose declaration changes mid-flight jumps. Identical inputs have to produce an
identical plan — no clock, no accumulating state — or the card would twitch once a minute for
ever. That is what the test named *"a refresh that changes no rows produces the identical
plan"* is for; it looks like a tautology and is the only thing standing between the panel and a
once-a-minute stutter.

### The harness learned to tell a deliberate clip from a silent one

Every check in `e2e/layout` said *nothing escaped*. A card that swallows its extra rows passes
all of them — that is exactly what the panel did before this wave, and why the sixth ticker was
invisible rather than broken. So:

- A section hiding a row carries **`data-scroll`**, and `docs/THEMING.md` now states that as
  part of the theme contract rather than as neon's implementation detail.
- `measure.js` reports an overflowing `data-scroll` section separately from a silently clipped
  one, and fails a section that claims the attribute with nothing hidden — motion for its own
  sake, on a panel in someone's peripheral vision (T6.6 step 2).
- `check_layout.py` has a third pass, `e2e/layout/overflow.js`, and it is the **only pass in
  the harness that requires something to happen** rather than requiring that nothing goes
  wrong. If the scroll regresses it fails; if the fixture stops overflowing because the cards
  grew, it also fails, rather than quietly measuring nothing.
- `overflowInside()` looks for the overflow where it now is. A section's own `scrollHeight` was
  enough until this wave put the rows two boxes down, and a nested `overflow: hidden` clips its
  descendants' contribution — so a card whose rows do not fit its inner window measures as
  fitting itself, which is the harness going blind in exactly the place the feature lives. It
  walks down and asks the question of any element bigger than the parent that clips it, in both
  axes, without being told a theme's class names.
- `paintedRect()` intersects a rect with the boxes that clip it, so a row waiting its turn
  below the fold is not reported as a card escaping the viewport. **Scoped to `[data-scroll]`
  on purpose.** The first cut clipped every rect against every `overflow: hidden` ancestor,
  which is more honest in the abstract and guts question 2 — `body` and `#panel` both clip, so
  a card that escaped the panel would have been intersected back inside it and reported as
  fine.

All four were mutation-tested when they were written: drop the attribute, set it
unconditionally, and the pass fails each way.

### A third browser check, because the hard requirement had no command

T6.6 calls one thing "the whole of the task's difficulty": the refresh must not restart the
scroll. Nothing in the repo could check it. `format.js` is pure and cannot see an animation;
`check_layout.py` measures a single frame; a screenshot shows a card that looks right either
way. A card whose animation restarts every 60 seconds walks a little way down, jumps back to
the top, and never reaches the rows it is moving to reveal — and every check in the repo passes.

`e2e/layout/check_scroll.py` drives it over time, on check_layout's Marionette plumbing so
there is still one browser harness: deliver an overflowing payload, sample the transform, wait
past the keyframes' hold, sample again, deliver the **identical** payload, and assert the
offset did not go back to zero. Plus two cheap ones that make a failure legible — a card that
declares a scroll and does not move, and a card that keeps a transform after its rows start
fitting again.

Two numbers in it were tuned against a real failure rather than guessed. It samples at eight
seconds, not five, because at five the card has moved 7px on a slow run — enough to prove it
moves, not enough to separate "carried across" from "restarted" by any threshold that also
tolerates the card still moving between samples. And the comparison is proportional, not
absolute: the first cut used ±8px, and the rebuild mutation slipped through it. At eight
seconds the two outcomes are 37px and 0.

It also calibrates the viewport, which `check_blackout.py` does not need to. Every number in
the file comes out of the card's height, and in whatever window Firefox happens to open, six
rows fit a card that holds three on the device — the check would have reported the feature
missing.

### The first animation on this page brought a rule with it

Nothing on the panel moved before this wave, so nothing had ever had to ask what a moving thing
does while the panel is dark. `visibility: hidden` does not stop a CSS animation — it keeps
ticking and its layer keeps being recomposited — and the two states the blackout covers are the
two where that is pure cost: offline the device is asleep on battery (ADR 0014), and too hot it
is being blanked *because* it is working too hard (ADR 0012).

So `web/css/style.css` pauses every animation under `:root[data-panel="dark"]`, beside the rule
that hides the body, and for the same reason it is there: it is the page's half of a promise
about hardware, and a theme that forgot it would look perfectly fine and quietly cost battery
overnight. `paused` rather than `none`, so the card comes back where it left off.

**This is T6.2's step 4** ("no animation while offline"), arrived at early because T6.6 is what
made it possible to get wrong. T6.2 keeps the step; it has nothing left to do for it.

`check_blackout.py` asserts it — an overflowing payload, the animation running while lit and
paused while dark — and it finds the moving element by its computed `animation-name` rather
than by a class, so it stays a statement about the contract and not about neon's markup. It was
mutation-tested: delete the declaration and the check fails.

### The review found seven things, and the two that mattered were invisible here

Everything in this wave passes on this machine, which is the problem with both of the real
findings: neither of them can fail on this machine.

- **A card would have twitched one pixel, for ever, on the phone only.** `clientHeight` and
  `scrollHeight` are integers and the device lays out at a device pixel ratio of 2.75, so a
  card whose rows exactly fill it can report 102px of content in a 101px window. That is one
  hidden row by every count in `format.js`, and a travel of one pixel: `data-scroll` set, a
  compositor layer held for the life of the panel, and a card moving a pixel back and forth
  every seventeen seconds in the corner of someone's eye — with **every check in `e2e/layout`
  passing**, because a pixel of overflow is a real overflow as far as a measurement can tell.
  `worthScrolling(travelPx)` is the fix, in `format.js` with the rest of the decision and
  tested there: below four pixels a card does not move however the row arithmetic came out.
  Reproduced by forcing a card 3px over its window — `data-scroll` before, none after.
- **A twelve-line comment explained a guard that did nothing**, twice. `flex: 0 0 auto` on the
  scroller was said to stop it shrinking to the window; a child of a block container is not a
  flex item, so it had no effect at all. The rewrite claimed making the window a flex column
  would break it — also false, because a flex item does not shrink below its min-content
  height either. Mutation testing found the edit that *does* break it: `min-height: 0` on the
  scroller inside a flex window, which is the kind of rule this file already has four of,
  added for unrelated reasons. The comment now names that, and says what happens — which is
  not "it passes every check": the overflow pass fails on all three cards, which is what that
  pass is for.

Three harness findings, all of which could only ever have produced a false report:
`check_blackout.py`'s new animation-pause block could be beaten by a `mock.js` tick held
across the dark window and flushed on the way back, reporting a correct panel as broken (it
stops the feed now, as `check_scroll.py` does); `check_scroll.py` raised a `TypeError` instead
of a sentence when the animation vanished between two samples; and its question 4 built a
`DOMMatrixReadOnly` from the string `'none'`, which Firefox reads as the identity matrix and
Chromium throws on — silently pinning a check to the wrong browser in a repo whose target is a
Chromium WebView.

Two cosmetic ones, both taken: `formatRange(null, 27)` rendered `--° / 27°`, a temperature of
nothing-degrees and the same species of unreadable string the function exists to stop (it is
`-- / 27°` now, unit on the numbers only); and `paintedRect()`'s one blind spot — an
absolutely positioned descendant of a scrolling card, whose containing block is outside the
box that appears to clip it — is now named in the comment. There is no such element today, and
`#battery` is exactly that shape elsewhere on the panel and is what earned question 4 in T5.4.

### One acceptance criterion was replaced rather than repaired

T6.6's second line was `! grep -n 'overflow: hidden' web/themes/neon/theme.css | grep -q
'card-list'`. It **could not fail** — the selector and the declaration are on different lines,
so the inner grep never matched and the `!` always succeeded — and what it asked for was wrong
anyway: the clip is what makes the scroll work, and removing it contradicts T6.1's acceptance,
which asserts that the same block clips. The fault was never the clip. It was that a card could
hide a row and say nothing, and that is what the replacement asserts.

That is the fourth acceptance block this hazard has cost, and the first one that was wrong in
its *intent* rather than merely pointed at a moved file. `make verify-accepted` — proposed
below, and still not written — would have found the first three and not this one; only reading
the line against the code it guards finds this one.

## Resuming after 2026-09-20 (wave 13)

Wave 13 is T6.7 alone, on `wave/13-theme-boundary`. **The panel's look is a directory now.**
`web/themes/neon/` is the design the project shipped, `web/themes/plain/` is the proof a second
one costs no core change, and `theme` in `server/config.toml` chooses between them without a
rebuild. `docs/THEMING.md` is the contract a contributor reads.

**Next: T6.6** (slow scroll when a card overflows), which was waiting on this and is now
unblocked. Its scroll is presentation, so it lands on the theme side of the new line — its
acceptance grep was repointed at `web/themes/neon/theme.css` during this wave. After that,
phase 6 still holds T6.2 (glow, micro-animations, burn-in shift), T6.4 (night profile) and the
new T6.8 (the weather card), all `todo` and all touching only `web/` — and all now touching a
*theme*, not the panel.

### Three tasks were written this wave and none of them was executed

Asked for on 2026-09-20, alongside T6.7 and recorded rather than built:

- **T6.8**, the weather card. The answer to "is there anything in the tasks about improving the
  weather design" was no, and there is now.
- **T8.1** and **T8.2**, a new phase: the two mute buttons under the clock. They are in their
  own phase because the feature spans the server, Java and the page, and because T8.2 needs
  T6.7 — the buttons are markup, so they belong to a theme, and writing them into `app.js`
  first would only have meant moving them.

Read each file before promising it is next; **T8.1 carries an ADR that has to be written before
its code**, and T8.2 cannot start without T8.1.

### Four acceptance blocks were repaired, and one was already broken

The move invalidated three, which is the hazard the section below this one describes, running
forwards:

- **T6.1** asserted `#D53FA7` and `var(--accent)` in `web/css/style.css`. The palette is in
  `web/themes/neon/theme.css`; both lines started exiting 1.
- **T6.3** asserted `! grep -qE 'font-size:\s*1?[0-9]px' web/css/style.css`, and that file now
  holds no font size at all — so it kept exiting 0 while asserting nothing. It is `-r` over
  `web/themes/` now, deliberately: the 20px floor was measured at this desk on this device, so
  it is a fact about the panel rather than about one theme's taste, and a new theme inherits it.
- **T1.2** asserted the mock guard in `web/index.html`. The guard is inside `web/js/mock.js`
  now, because a script injected from an inline block cannot be placed in the deferred list and
  could run before `window.onData` exists.

The fourth is the interesting one. **T6.1's `! grep -qE 'overflow:\s*visible' web/css/style.css`
was already failing on `main`, and had been since T6.5** — the sparkline sets `overflow: visible`
on its `<svg>` so a stroke on the box's edge is not shaved off. The rule was guarding a *card*
letting its rows escape, and a file-wide grep cannot tell the two apart. It is now a scoped
assertion that the shared `.card-list, .card` block clips, and it was mutation-tested: flip that
one declaration to `visible` and it exits 1.

That is the first time this hazard has produced a defect with **nothing to do with the task
that broke it**. T6.5 changed a file, an unrelated `done` task's criterion stopped holding, and
five waves passed with nobody looking. `make verify-accepted` — proposed below and still not
written — is the thing that would have caught it the same day.

## Nothing re-runs an earlier task's acceptance

T3.1 was accepted with both its commands exiting 0. T3.2 then landed the hard fail on a missing
`config.json`, and T3.1's `probe.py --serve --expect up` started exiting 2 — without a line of
T3.1's own code changing, and without anything reporting it. It was found only because a
verifier was pointed at the whole branch rather than at one task.

That is a gap in the workflow, not bad luck. `/task` runs a task's acceptance once, at the
moment that task is executed, and nothing ever runs it again. `make check` runs the **test
suites**, not the `## Acceptance` blocks, so a later task can silently invalidate an earlier
task's criterion and the index will keep saying `done`.

Worth a task of its own: a `make verify-accepted` that re-runs the acceptance block of every row
marked `done` and fails on the first non-zero exit. Until that exists, treat `done` as "passed
once", not as "passes now".

## Why `probe.py` moved from T3.5 to T3.1

T3.1 declared `Prereqs: none` and `Files: server/server.py`, but both of its acceptance
commands run `server/probe.py` — a T3.5 deliverable. T3.5 declared `Prereqs: T3.1, T3.2`. So
T3.1 needed T3.5 needed T3.1, and neither could go first.

`scripts/check_status.py` detects prereq cycles and did not catch this one: it compares
**declared** prereqs, and this cycle ran through an **acceptance command** instead. Worth
remembering — the same shape is what made T1.2 unrunnable before TT.1.

`probe.py` is a generic HTTP probe that knows nothing about login scope, and ten task files call
it. It belongs with its first caller. T3.5 keeps `verify_login_scope.py`, which really is part
of the login-scope contract.

## Why TT.1 runs before T1.2

The table used to list T1.2 before TT.1. T1.2's acceptance ends with
`node --test "web/test/**/*.test.js"`, and the only thing that ever writes a file matching that
glob is **TT.1**. Run in the table's order, T1.2's last line fails on an empty glob and the task
can never go green — through no fault of its own implementation.

TT.1's own prereq is T1.1, not T1.2, so nothing is lost by swapping them: `format.js` is
extracted from the clock code, and `mock.js` then feeds the payload through functions that are
already under test.

## Why T7.1 sits in phase 2

The task says "do this **early**" in its own first paragraph, and `docs/BUILD.md` says "use the
release keystore from the start, including for local builds" — while the table had it last, in
phase 7, after T2.4 has already installed a debug-signed APK. Android refuses to install a
differently-signed APK over an existing one, so the only way out is an uninstall, which throws
away the device state and every MIUI permission T2.4 spent a session granting. That is exactly
what T7.1 exists to prevent, and the old ordering guaranteed it.

Moving the row was not enough, though: T7.1 landing also invalidated **T2.2's acceptance
block**, and nothing reported it — the same failure mode as "Nothing re-runs an earlier task's
acceptance" above, running forwards instead of backwards. A task marked `todo` can be quietly
broken by a task that lands before it, and there is no check for that either. T2.2's block
asked for `out/desk-panel-debug.apk`, a path the build stopped producing when T7.1 gave only
the release artefact a product name, and it installed the debug APK, which is precisely the
debug-first install this section exists to prevent. Both were rewritten during T2.2; the task
file carries the detail.

The third defect found there was older than T7.1 and unrelated to it: the block ran
`adb install` and then grepped `dumpsys window` for `mCurrentFocus.*dev.bosco.deskpanel`,
without ever starting the Activity. `adb install` launches nothing, so that line was asserting
against whatever happened to be foreground — it would have passed with the app installed and
never run, and failed for someone whose launcher happened to be showing. An acceptance command
can exit 0 for reasons that have nothing to do with the task; that one had been sitting in the
file since T0.5's remediation pass, which converted prose criteria into commands but could not
tell whether the resulting command measured the right thing.

A fourth defect was introduced by the rewrite itself, and is worth recording because the next
task that greps a marker will hit it. The replacement block kept the original's
`adb logcat -c && sleep 10 && ! adb logcat -d | grep -q ...` line and appended a grep for the
new `panel=rendered` marker — but that marker is emitted once, by `onPageFinished`, during
`am start`, which runs *before* the line that clears the buffer. The clear wiped the evidence,
and the block failed red against a perfectly healthy panel. Ordering is now explicit:
`force-stop`, `logcat -c`, `am start`, `sleep`, then every grep. The `force-stop` is the other
half of it — `am start` on an already-foregrounded Activity reloads nothing, so `onPageFinished`
never fires and the marker never reappears on a re-run.

`scripts/check_acceptance.py` also gained a fix here: its non-terminating rule flagged
`adb logcat -c`, on a regex that demanded `-d`. `-c` clears the buffer and exits immediately, so
that was a false positive blocking a correct block. The rule now accepts `-d` or `-c` and still
catches a bare `adb logcat`, `adb logcat | grep`, and `adb logcat -v time`.

## Shortest path to seeing something work

`T1.1 → T0.1 → T2.1 → T7.1 → T2.2` puts a running clock on the phone, signed with the key it
will keep. T1.1 comes first now: it needs only `node`, so it does not wait on the container.

Then `T3.1 → T3.5 → T3.8|T3.9 → T4.1 → T4.2 → T4.3` delivers the actual product behaviour.
Quotes and weather come afterwards; they are the least risky part and the easiest to defer.

## Open questions

- ~~**brapi FX and crypto endpoints are unconfirmed**~~ **Resolved 2026-09-19, T3.3 subtask 0:
  brapi serves neither without a token.** `/api/v2/crypto` and `/api/v2/currency` both answer
  `401 MISSING_TOKEN`, while stocks answer 200 for the free sample set. The fallbacks are what
  ships — Binance for crypto, AwesomeAPI for FX, both key-free. Measured against the live API;
  the docs name the endpoints without giving their shapes. Recorded at the top of
  `server/providers_brapi.py`.
- **adb from inside the container is undocumented.** Answered: the container does not own the
  USB device. Gradle runs in the container and talks to the **host's** adb server over TCP —
  `make connected`, defined in TT.7. T7.2 covers wireless adb, which is a different question.
- ~~**Whether MIUI wakes the screen reliably**~~ **Resolved 2026-09-19, T4.4: it does.** ADR 0005
  keeps its primary design and now says so. The catch is not in the API but around it — MIUI's
  *Show on Lock screen* permission has to be granted or the wake is denied silently, and
  Developer options → *Stay awake* has to be off or the screen never sleeps to begin with.
- **Whether the local model can carry a task end to end** is what the two-agent setup is for.
  Resolved per task, by reviewing the PR. See ADR 0011 and `docs/LOCAL-MODELS.md`.
- ~~**Who keeps polling once the Activity is not resumed**~~ **Resolved 2026-09-19, T4.3:** a
  started foreground service, `PanelService`, with a `PARTIAL_WAKE_LOCK` held for the offline
  stretch only. Written up in [ADR 0014](../docs/adr/0014-poll-loop-outlives-the-screen.md),
  including why the wake lock is affordable here and what has to be built if that stops being
  true.
- **Whether the wake lock stays affordable** is the one this opened in its place. It rests on
  the board keeping USB powered with the PC off, which is true of this desk and is the opposite
  of what `DEVICE-CARE.md` recommends. Disabling ErP Ready would make the phone discharge
  through every offline hour with the CPU pinned awake, and the fix — drop the lock while
  discharging, sparse `AlarmManager` probe, `ACTION_POWER_CONNECTED` as the real signal — is
  specified in ADR 0014 and deliberately unwritten, because it cannot be tested on this desk.

## Resuming after 2026-09-19 (wave 9)

Wave 9 is on `wave/9-resilience-and-battery`. **The panel survives a flaky network, backs off
while the PC is away, and reports its own battery.** T5.2, T5.3 and T5.4 are `done`; every
acceptance command in all three exits 0 on the real device.

What that looks like from outside: drop the phone's Wi-Fi and the panel notices, sleeps the
screen, and retries at 2, 4, 8, 15, 15 seconds until it comes back — 4 probes a minute while
the PC is off, and no data requests at all. Bring it back and the screen wakes within 15s with
the data poller running in the same second. The bottom-right corner now reads `BAT 22% ·
25.2°C`, and goes amber above 40.

**Next: T5.5** (thermal screen cutoff), which now has both halves it was waiting for — the
screen-state machine from T4.3/T4.4, and a temperature to act on from T5.4. It amends invariant
3 by way of ADR 0012, so read that before writing any of it. After that the phase is empty and
T6.x is the natural continuation; T6.6 and T6.7 are both `todo`, both touch only `web/`, and
T6.6 wants T6.7 first.

### Two acceptance blocks were wrong and are fixed

Both in the same way TT.6's was, and both were **passing** while proving nothing:

- **T5.2** cleared the logcat buffer *after* the outage it was testing, then asserted
  `grep -q 'state='` to show the poller was alive. `state=` is a transition marker, so a healthy
  panel that has been online for a minute logs none — run verbatim here it reported `note: no
  state= in a steady-state window` on a device that was working perfectly. It now clears before
  the Wi-Fi is dropped and asserts on `ping=ok`.
- **T5.3** counted `ping=` lines to prove the backoff. Nothing emitted `ping=` — `Markers.ping`
  had been defined by TT.6 and wired to nothing — so `-le 4` was satisfied by a count of zero.
  `PcPoller` emits it per probe now.

The pattern is worth naming, because it is three for three: **an assertion that passes on a
log nobody has proved contains anything is not an assertion.** Check that the marker you are
counting is emitted by something before trusting the count.

### The layout harness now measures overlap, and that is new

`check_layout.py` asked three questions — does the page scroll, is anything outside the
viewport, does any section clip its own content — and **none of them is "is one section drawn
on top of another"**. T5.4's corner line is positioned absolutely, so it was free to land on
live content, and it did: the harness reported PASS on a panel with a black box over the
crypto card's last row. Worse, the stress fixture used `charging: true`, so the widest battery
line the code can produce was never rendered in either pass.

`measure.js` now compares **ink against ink** — the text-bearing leaves and each sparkline's
`<path>`, for every pair of sections. Boxes would have been the wrong comparison: `#battery`
shares a rectangle with the WEATHER card by design, and so does `#stale-badge` with `#panel`,
so a box check would either fail on both or have to allowlist the exact pair the bug was in.
Sharing empty space is fine; sharing a pixel with a glyph in it is not.

The fixture is fixed too (`charging: false`), so the 323px variant is measured on every run.
**T6.6 and T6.7 both move markup around** — that is what they are for — so this check is worth
more to them than it was to T5.4.

### What is still only true on this desk

- **The DEVICE corner says 22%, and that is not a healthy number.** The phone was at 22% and
  charging (`status: 2`, USB powered) through this wave, which means it had been running the
  battery down. ADR 0014's wake lock is affordable *only* while the board keeps USB powered with
  the PC off; if this phone is arriving at the morning under 30% the assumption has stopped
  holding, and the power-aware branch specified in ADR 0014 is the work to do. The new corner
  line is what makes that visible without `dumpsys`.
- **The server is still started by hand** and T3.9 is still `todo`. This wave stopped and
  restarted it for T5.3's acceptance; it is running again, detached, logging to the session
  scratchpad rather than to wherever it was before. Stop it **by PID**, found through
  `ss -ltnp 'sport = :8777'`, never `pkill -f "server/server.py"`.
- **B3 now carries real rows** — PETR4, SEER3 and TAEE11 render with prices and sparklines — so
  a brapi token has been put in `server/config.json` since wave 8's note. That note is no longer
  true and has been dropped.
- **Crypto and FX do not come from brapi at all** — it answers `401` for both without a token.
  Binance and AwesomeAPI serve them, key-free. If either changes shape the panel loses that
  card, not the whole page.
- **One paid ticker 401s the whole brapi request**, so a B3 list is all-free or all-paid: PETR4
  would not survive alongside SEER3 without a token covering both. The free sample set is
  PETR4, MGLU3, VALE3, ITUB4.
- **The battery broadcast fires about every eight seconds** on this device while charging. That
  is why the render is deduplicated rather than pushed straight through, and it is a device
  fact, not a guarantee: a phone that broadcasts rarely would show a level that lags by that
  much. Nothing polls to cover it, deliberately (T5.4 step 5).

### The rig, unchanged from wave 7

1. **Start the server by hand** — `python server/server.py`. Start and stop it **by PID**, never
   `pkill -f "server/server.py"`: that pattern matches the command line of the shell doing the
   killing, and it killed the session twice in wave 7.
2. **The ufw rule has to be in place** — `sudo ufw allow from 192.168.0.0/16 to any port 8777
   proto tcp`. The phone arrives through a NAT, so the rule cannot name the phone's own address.
   `toybox nc` from `adb shell` is the quickest check that it still is.
3. **Be at the phone for the first `adb install` of the session**, build with `assembleRelease`,
   and **re-grant the MIUI app-ops afterwards** — `adb install -r` resets them and the screen
   silently stops waking:
   `adb shell appops set dev.bosco.deskpanel 10020 allow` (and `10008`).
4. **Developer options → "Stay awake" must stay off.** `adb shell settings get global
   stay_on_while_plugged_in` has to answer `0`.
5. **`PANEL_ORIENTATION=reverseLandscape` in `.env`** is this stand's direction (`ROTATION_270`).

**Always `adb logcat -c` before changing the PC's state, never after.** The reverse order is a
race the clear usually wins, leaving an empty log and an app that did everything right.

The server's own log prints one line per request with a timestamp, so the panel's poll cadence —
2s for `/ping`, 60s for the data pair — is directly countable without touching the app. The app
now says the same thing from its own side: `ping=` per probe, `data=` per cycle.

## Resuming after 2026-09-20 (wave 11)

Wave 11 is T5.5 alone, on `wave/11-thermal-cutoff`. **Invariant 3 now has two authorities**: the
screen is lit only when the PC is online *and* the device is below 45 °C, and it comes back at
38. The DEVICE line reddens through amber at 40 and red at 43 on the way there, which is the
half that keeps a black panel from being read as "the PC died".

**Next: T3.12** (config in TOML). It is the only `todo` in phase 3 that needs no hardware, and it
is what unblocks T6.7, which in turn unblocks T6.6 — read the `Prereqs:` lines rather than the
phase order. T5.5 was the last of phase 5, so phase 6 is the natural continuation after that.

Four new task files, **T7.4 to T7.7**, carry the documentation and repo-opening work that was
asked for on 2026-09-20 and is meant to run at the end: phone setup checked against the official
Android docs, a local-run tutorial for a contributor with no phone and no model, a contribution
guide with commit and PR templates, and the strategy and settings for opening the repo. T7.3 now
declares all four as prerequisites and carries the README's final pass.

### Two acceptance blocks were wrong, which makes five

- **T5.5's own.** `screen=thermal` is a prefix of `screen=thermal-clear`, so `grep -q
  'screen=thermal'` matches the line saying the panel came *back*. An implementation that never
  blanked but logged the clear would have passed. Every assertion anchors the end of the line now.
- **TT.6's**, and this one was **failing on `main` while protecting nothing**. `grep -rn
  'state=\|screen='` fires on any javadoc that *names* a marker, and this repo's javadoc names
  them constantly — explaining why `screen=thermal` is not `screen=sleep` is the whole reason the
  pair exists. Three hits, all prose. It matches quoted strings now, which is the property that
  was meant: no marker *built* anywhere but `Markers.java`.

The pattern from wave 9 holds and is worth restating: **an assertion nobody has proved can fail
is not an assertion.** Both of these passed, or were ignored, for exactly that reason.

### The reviews found what the device could not, twice

The first cut logged the thermal marker at the verdict. That is wrong in a sequence no test on
this desk would have produced: the phone gets hot overnight with the PC away, `screen=thermal` is
logged while *nothing blanks* because the display is already out, and the morning's login then
brings the panel up black with only `screen=wake` in the log — both halves backwards from what
ADR 0012 promises the marker means.

Moving it to `MainActivity.setBlanked` was the first fix and **it did not work**, which the second
review caught: heat's veto deliberately does not consult the PC, so the blanking still happened —
and still logged — with the display already out. The marker reports the *conjunction* now,
`online && tooHot`, and lives in `PanelService`, the only component that holds both halves and the
only one that survives the Activity recreation every wake from doze causes.

Fourteen findings across the two rounds, eleven applied. The three declined have their reasons
written next to the code, not in a commit message where nobody tuning the constant will look.

**The lesson worth keeping: both rounds found things no run on this desk would have produced.**
The device was only ever hot while somebody was watching it, and every defect here lived in the
state where it is hot while nobody is.

### What is still only true on this desk

- **`Max charging current` is not a measurement.** It moved through 50000, 100000, 150000, 200000
  and 250000 in one session on 2026-09-20 with nothing touched, and had been stuck at 50000 until
  the cable was reseated — while the framework called that state `AC powered: true`. It is
  instantaneous and renegotiable, so a single reading of it establishes nothing, including the one
  `DEVICE-CARE.md` had been quoting since 2026-09-19. That file now carries the numbers and the
  method: the trustworthy measure is the level trend over hours. **A reseat is a real
  intervention** — the port can sit in a worse state indefinitely with nothing to say so.
- **`dumpsys battery set temp` sticks until `reset`.** A forgotten injection is indistinguishable
  from a real thermal fault, and the panel will sit black with the PC plainly on. Every T5.5 run
  ends with `adb shell dumpsys battery reset`; check `temperature:` afterwards.
- **The manual check is outstanding.** The temperature has only ever been injected on this desk.
  Watching the DEVICE line go amber then red *before* the screen blanks is what proves the
  sequence is legible, and it needs a genuinely warm phone.
- **`server/config.json` is mode 0644** and holds the brapi token; the server warns about it on
  every start. Fixing it is one `chmod 600`, and T7.3's secret audit will want it done.

## Resuming after 2026-09-20 (wave 12)

Wave 12 is T3.12 alone, on `wave/12-config-in-toml`. The runtime config is `server/config.toml`
now, and `server/config.example.toml` is the deliverable — the format change is the convenience,
the catalogue is the thing. An owner can answer "which tickers can I put here?" without opening
a `.py`, which was the actual complaint.

**Next: T6.7** (a theme boundary), which T3.12 was blocking and which then unblocks T6.6. Read
the `Prereqs:` lines rather than the phase order. `theme` is already in `DEFAULT_CONFIG`, already
in both example files and already defaulted to `neon`; what T6.7 has to add is delivering it in
the payload and the `web/themes/<name>/` split.

### Nothing here was a new capability, and two old things were wrong anyway

Config has driven tickers without a rebuild since T3.2. What this wave found while moving the
format is worth more than the format:

- **`config.example.json` shipped a 300-second quotes interval against a 600-second default.**
  The comment beside `DEFAULT_CONFIG` has spelled out since T3.3 why 300 is wrong — three
  tickers, one request each, 25,920 requests a month against brapi's 15,000, so the B3 card goes
  permanently stale around the 17th. The documented first step was `cp config.example.json
  config.json`, so the default nobody would have chosen was the value everybody got. It is 600
  now, and a test fails the build if an example ever drops below the default again.
- **The example was missing three keys entirely** (`brapi_symbols_per_request`,
  `history_interval_s`, `history_days`). A key that exists only in `DEFAULT_CONFIG` is a key no
  owner finds out about. The key sets are now asserted equal in both directions, for both files.

### The catalogue was checked, not recalled

Every fact in `config.example.toml` came from either this repository's own measured notes or a
live endpoint, never from memory. AwesomeAPI lists 540 pairs at `/json/available`; Binance lists
3,708 symbols at `/api/v3/ticker/price`; every pair and coin the example names was confirmed
present in those listings before being written down. The four free brapi tickers come from
`providers_brapi.FREE_TIER_SYMBOLS`, and a test now asserts the example still names all four —
a catalogue that drifts from the provider is worse than no catalogue.

**The task file itself had a fact wrong**, and the example says the corrected version: "one paid
ticker 401s the whole request" holds only when `brapi_symbols_per_request` is raised above 1. At
the shipped value each ticker is its own request and `load` already loses only that ticker's row.
The file the owner reads should not repeat a simplification from the file the owner never sees.

### The review found four, and the worst was advice that would have done nothing

- **The migration notice was printed for explicit `--config` paths too.** `config_search_paths`
  deliberately never upgrades a path somebody passed — that rule is what stops a launcher
  pointing at a deleted file from starting on the repository's config — and *every installed
  launcher passes one*: `install_task.ps1` bakes an absolute `--config …\server\config.json`
  into the Scheduled Task. So the line said "copy the example to config.toml" to the one
  audience for whom doing that changes nothing. An owner would have moved their tickers and
  their brapi token into a file nothing reads, restarted, and seen the old panel with no error
  to explain it. The notice now knows which source won and tells an explicit path to change the
  path — re-run the installer — rather than to add a file.
- **`docs/SERVER-SETUP.md` told that same owner to delete `config.json` afterwards**, which
  does not merely fail to help: the task exits 1 at every logon, under `pythonw`, with no
  console, and the phone reports offline forever — the DHCP-drift failure's exact symptom. The
  migration is now written twice, once for a hand-started server and once for the Scheduled
  Task, with re-running the installer as the step between copying and deleting.
- **The key-set guard only ever checked the TOML example.** The cross-file test compared the two
  *after* the DEFAULT_CONFIG merge, so any key whose example value equals its default was
  invisible — `theme`, `port`, both intervals, `actions` and four more. Deleting `theme` from
  `config.example.json` left all 137 tests green while `server/CLAUDE.md` claimed the twin was
  kept in step. Both examples are now read raw and compared key-set to key-set, and that
  mutation fails the suite.
- **The example documented a theme fallback that does not exist.** "An unknown name falls back
  to neon and says so once in the log" is T6.7's promise; nothing reads `theme` today, so an
  owner setting `theme = "amber"` would get an unchanged panel, no log line and no error — in
  the one file whose whole purpose is to be the authoritative catalogue of what works. The key
  is now marked reserved and unread until T6.7.

Three of the four are the same mistake in different places: **a statement that was true of the
code's happy path and false for the way the thing is actually installed.** The fourth is an
assertion that could not fail, which is wave 9's lesson arriving for the third time.

### What is still only true on this desk

- **The Windows installer's half is unverified.** `Resolve-DeskPanelConfig` and the TOML branch
  of `Get-ConfiguredPort` are written and reviewed; no PowerShell exists on this machine, so
  neither has been *run*. Both degrade the way the surrounding code already degraded — a port
  the scan cannot find falls back to 8777 with a warning — but T3.8 is still the task that
  proves it on the box. Re-run `install_task.ps1` there before trusting it.
- **The server on this desk was restarted onto the new code** (stopped by PID from
  `ss -ltnp 'sport = :8777'`, as ever) and still loads `server/config.json`, because that is the
  only config file this machine has. The notice fires on every start, which is the transition
  working rather than a defect.
- **`server/config.json` is still mode 0644** and holds the brapi token; the server warns about
  it on every start. Fixing it is one `chmod 600`, and T7.3's secret audit will want it done —
  and will want it done to `config.toml` if the migration happens first.
