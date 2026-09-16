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
| T2.1 | Minimal Gradle project in Java | todo | Needs T0.1 |
| T2.2 | WebView + WebViewAssetLoader | todo | 🏁 **Milestone A** — first sign of life |
| T2.3 | Keep screen on, landscape, immersive | todo | |
| T7.1 | Release keystore and signing | todo | Moved here from phase 7 — see below |
| T2.4 | MIUI smoke test: autostart, battery, reboot | todo | Deliberately early. Riskiest unknown |

## Phase 3 — Python server (parallel with phase 2)

| # | Task | State | Notes |
|---|---|---|---|
| T3.1 | `/ping` | done | 2026-09-16. `server/server.py` (`/ping` + 404) and `server/probe.py` (stdlib-only HTTP probe, `--serve` starts/stops the server). Both acceptance commands exit 0 |
| T3.2 | Config loading | blocked | 2026-09-16. `load_config(path)` in `server/server.py`: defaults for missing keys, `ConfigError` for malformed JSON, hard fail (exit 1, message points at `config.example.json`) when the file is absent — deliberately, per the task's own guidance against a silently-empty start. 3 of 4 acceptance commands pass; `probe.py --serve --expect up` fails in this checkout because `server/config.json` (gitignored, per-machine) does not exist here and creating it is outside what this session is permitted to touch. Needs a human to `cp server/config.example.json server/config.json` once (`docs/SERVER-SETUP.md`), then re-run |
| T3.3 | `/quotes` proxy | todo | ⚠️ Subtask 0: confirm brapi FX and crypto endpoints |
| T3.4 | `/weather` proxy | todo | |
| T3.5 | Login-scoped autostart: contract + `probe.py` | todo | Platform-neutral. Rewritten — see ADR 0010 |
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
| T4.1 | `network_security_config.xml` | todo | |
| T4.2 | `PcPoller` | todo | |
| T4.3 | Wire to `onPcState()` + brightness | todo | 🏁 **Milestone B** — the product's soul |
| T4.4 | Real screen sleep, replacing brightness zero | todo | Decides the ADR 0005 fallback |
| TT.5 | `PcState` extracted + JVM tests | todo | Pairs with T4.2, T5.3 |
| TT.6 | Logcat markers | todo | Silent prerequisite of the whole E2E suite |

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
