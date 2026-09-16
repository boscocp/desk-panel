# Status

The index. Take the first task that is not `done`, read **only** that task file, execute it,
run its acceptance command, then come back and update this table.

A coding task is not `done` until its paired test task is green.

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
| T0.6 | **Two-agent setup: `reasonix.toml`, model pinning** | todo | ⬅ **start here.** Landed by PR #1 outside the task system; ADR 0011 |

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
| T2.3 | Keep screen on, landscape, immersive | blocked | 2026-09-16. Needs the phone on adb: three `dumpsys` greps plus a 600s wakefulness check |
| T7.1 | Release keystore and signing | done | 2026-09-16. Keystore created by a human; `build.gradle.kts` reads `keystore.properties` and signs `release`, falling back to the debug key when the file is absent so a fresh clone still builds. APK at `out/desk-panel-release.apk`; `apksigner --print-certs` confirms the release DN, not `CN=Android Debug`. All six acceptance commands exit 0. Install-over check still manual |
| T2.4 | MIUI smoke test: autostart, battery, reboot | blocked | 2026-09-16. Needs the phone on adb: reboots it and asserts MIUI autostart, battery whitelist |

## Phase 3 — Python server (parallel with phase 2)

| # | Task | State | Notes |
|---|---|---|---|
| T3.1 | `/ping` | done | 2026-09-16. `server/server.py` + `server/probe.py`. Went blocked when T3.2 made a missing config fatal, green again once `config.json` was seeded — no T3.1 code changed either way |
| T3.2 | Config loading | done | 2026-09-16. Pure `load_config` with defaults; hard fail on a missing `config.json`. All four acceptance commands exit 0 |
| T3.3 | `/quotes` proxy | todo | ⚠️ Subtask 0: confirm brapi FX and crypto endpoints |
| T3.4 | `/weather` proxy | todo | |
| T3.5 | Login-scoped autostart: contract + verifier | done | 2026-09-16. `server/verify_login_scope.py` + `server/fixtures/login_scope/`. No installer here — T3.8/T3.9/T3.10 still `todo`. `probe.py` was left alone: it shipped with T3.1 and the login-scope work needed no flag it lacks. Every check is a pure function over captured text (`parse_schtasks_xml`, `parse_systemctl_show`, `parse_launchctl_print`, `parse_list_dependencies`, `parse_launchagent_plist`, `detect_autologin`, `detect_system_scope`, `detect_wsl`, `detect_container`) with command execution in a thin shell, so `--self-test` exercises all three platforms from fixtures on one box — 85 cases, and macOS is checkable without a Mac (TT.10's groundwork). **Fails closed**: exit 0 all pass, 1 a real failure, 2 could-not-tell, and a missing command or unreadable file produces 2, never 0. Proved twice — `PATH=/nonexistent` gives 2, and `docker run python:3.13-slim` gives 1 on `not-container` with everything else unknown. Linux fixtures are real captures from this machine (a `desk-panel.service` user unit was installed, enabled, captured in both the good and the `default.target` shapes, then removed); Windows and macOS fixtures are written to the documented output shapes and are the weak spot until T3.8/T3.10 replace them with real captures. On this box the live run exits 1 on `linux.unit.loaded` — correct, T3.9 has not installed the unit. `docs/SERVER-SETUP.md` rewritten: the `## Linux` section now carries the three mandatory fields instead of `WantedBy=default.target`, the title lost "(Windows)", the two `curl` lines became `probe.py`, and a `## Verifying the login scope` section documents the three exit codes. All four acceptance commands exit 0 |
| T3.8 | Windows: Scheduled Task, firewall, static IP | todo | Primary platform. Tested from the LAN |
| T3.9 | Linux: systemd user unit (graphical-session) | todo | Dev box. Beware `Linger=yes` |
| T3.10 | macOS: LaunchAgent | blocked | No Mac. Plist and docs ship anyway |
| T3.11 | Server portability hardening | done | 2026-09-16. `config_search_paths()` (`--config` → `DESK_PANEL_CONFIG` → `script_dir/config.json`, cwd-independent), `config_permission_warning()` (POSIX-only, warns not refuses), `check_python_version()` (3.11 floor), `Server(HTTPServer)` with `allow_reuse_address = os.name != "nt"`, `--check-only` and `--log-file` flags, explicit UTF-8 everywhere. All 5 acceptance commands exit 0 |
| T3.6 | Serve the APK at `/app` | todo | |
| T3.7 | `POST /action/{id}` stub returning 501 | todo | v2 placeholder |
| TT.2 | Server unit tests + fixtures | blocked | 2026-09-16. 32 tests, all green, no network. Covers every pure function that exists today: `load_config` (extended with the non-dict-JSON branch), `route`, `config_search_paths`, `config_permission_warning`, `check_python_version`, and a new `_allow_reuse_address(os_name)` extracted from `Server` so both platform branches are reachable without reloading the module (reloading under a patched `os.name` crashes on `Path(__file__).resolve()`). Fixtures and normalise/cache/stale-fallback tests are NOT done: `providers_brapi.py`/`providers_openmeteo.py` don't exist yet (T3.3/T3.4 are still `todo`), so there is no outbound call to patch and no real upstream shape to record a fixture from. Re-open once T3.3/T3.4 land |
| TT.3 | Two HTTP integration tests on port 0 | blocked | 2026-09-16. `server/tests/test_http.py`: `Server(("127.0.0.1", 0), Handler)` on a daemon thread, real `http.client` round trips, shut down and joined in `tearDownClass`. `GET /ping` (status, `Content-Type`, `Content-Length`, body bytes) and `GET /nonexistent` (404) are covered. `GET /quotes` (step 5) and `POST /action/x` → 501 (step 6) are NOT covered: `route()` in `server/server.py` still only handles `GET /ping`, so T3.3 ("`/quotes` proxy") and T3.7 ("`POST /action/{id}` stub") haven't landed and there is nothing to hit — `POST /action/x` still falls through to 404 today. Re-open once T3.3/T3.7 land, same pattern as TT.2. `python -m unittest discover -s server/tests -t .` exits 0, twice in a row, no port conflicts |
| TT.4 | Contract tests, opt-in | todo | |
| TT.10 | Login-scope verifier tests, from fixtures | todo | Makes T3.10 checkable without a Mac |

## Phase 4 — The core behaviour

| # | Task | State | Notes |
|---|---|---|---|
| T4.1 | `network_security_config.xml` | done | 2026-09-16. `res/xml/network_security_config.xml` grants cleartext to one `<domain-config>` and nothing else; no `base-config`, no `android:usesCleartextTraffic`. `includeSubdomains="false"` because a bare IP has no subdomains and the default would widen the exemption. Manifest gains `INTERNET` and `android:networkSecurityConfig` on `<application>`. Address is the agreed placeholder `192.168.1.100` — the DHCP reservation belongs to T3.8, which is `blocked` on the Windows PC, and T7.3's acceptance requires exactly this literal in committed non-doc source, so the placeholder is the correct committed value either way; a comment in the file says what to change. All five acceptance commands exit 0. Verified past the greps: `aapt2` on `out/app-debug.apk` shows the manifest attribute resolving to `@0x7f010000` = `xml/network_security_config`, and the packaged binary XML decodes to the single pinned domain |
| T4.2 | `PcPoller` | blocked | 2026-09-16. Needs the phone on adb: all four criteria are `adb logcat` marker greps |
| T4.3 | Wire to `onPcState()` + brightness | todo | 🏁 **Milestone B** — the product's soul |
| T4.4 | Real screen sleep, replacing brightness zero | todo | Decides the ADR 0005 fallback |
| TT.5 | `PcState` extracted + JVM tests | done | 2026-09-16. `PcState.java` is plain Java — no Android imports, no clock read internally, no threads, no sleeps: every time-aware method takes `nowMs` as an argument, so T4.2 can drive it unmodified. It owns the state (`UNKNOWN`/`ONLINE`/`OFFLINE`, starting `UNKNOWN` so the first probe either way is a transition), the consecutive-failure count, `nextIntervalMs()` (2000 online; 2000/4000/8000 doubling, capped at 15000 offline, reset on first success), and `nextProbeAtMs()`/`isDue()` so `PcPoller` can keep no deadline of its own. It decides *that* a transition happened and returns it; emitting `state=online`/`state=offline` stays on the Android side (TT.6). 16 JUnit tests; both acceptance commands exit 0 and `./gradlew test` finishes in seconds. The suite was checked against 10 mutations of `PcState` — flapping, deaf, stuck, uncapped backoff, no reset, flat backoff, backoff one rung too fast, `isDue` off by one, deadline ignoring the backoff, failures uncounted — and every one turned it red |
| TT.6 | Logcat markers | blocked | 2026-09-16. Needs the phone on adb: captures logcat and counts markers |

## Phase 5 — Real data

| # | Task | State | Notes |
|---|---|---|---|
| T5.1 | `DataPoller`, replacing the mock | todo | |
| T5.2 | Timeouts, retry, failure tolerance | todo | |
| T5.3 | Adaptive polling with backoff | todo | Requirement, not polish — see ADR 0008 |
| T5.4 | Battery telemetry | todo | |
| TT.7 | Espresso-Web assertions | todo | |

## Phase 6 — Visual (parallel with 3–5, touches only `web/`)

| # | Task | State | Notes |
|---|---|---|---|
| T6.1 | Landscape layout, neon palette | todo | |
| T6.2 | Glow, micro-animations, burn-in shift | todo | |
| T6.3 | Legibility on the physical device | todo | |
| T6.4 | Night profile | todo | |

## Phase 7 — Packaging

| # | Task | State | Notes |
|---|---|---|---|
| T7.2 | Wireless adb from the container | todo | May fall back to host platform-tools |
| T7.3 | Pre-public review: secrets, README, screenshots | todo | Before flipping the repo public |
| TT.8 | `e2e/run_e2e.py`, five scenarios | todo | Needs TT.6 |
| TT.9 | CI workflow | todo | |

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

- **brapi FX and crypto endpoints are unconfirmed.** Resolved as subtask 0 of T3.3. Fallbacks
  without a key: Binance public API for crypto, AwesomeAPI for FX.
- **adb from inside the container is undocumented.** Answered: the container does not own the
  USB device. Gradle runs in the container and talks to the **host's** adb server over TCP —
  `make connected`, defined in TT.7. T7.2 covers wireless adb, which is a different question.
- **Whether MIUI wakes the screen reliably** decides whether ADR 0005 keeps its primary design
  or falls back. Resolved in T4.4, which must write the outcome into the ADR before it closes —
  0005 is marked `accepted` today with its central mechanism still undecided.
- **Whether the local model can carry a task end to end** is what the two-agent setup is for.
  Resolved per task, by reviewing the PR. See ADR 0011 and `docs/LOCAL-MODELS.md`.
