# Status

The index. Take the first task that is not `done`, read **only** that task file, execute it,
run its acceptance command, then come back and update this table.

A coding task is not `done` until its paired test task is green.

Legend: `todo` · `wip` · `blocked` · `done`

## Phase 0 — Foundation

| # | Task | State | Notes |
|---|---|---|---|
| T0.0 | Git identity and repository creation | done | Bootstrap session, 2026-09-13 |
| T0.1 | **Containerised Android toolchain** | todo | ⬅ **start here.** Blocks all of phase 2. Big one |
| T0.2 | Repository skeleton, README, gitignore, gitattributes | done | Bootstrap session |
| T0.3 | The nine ADRs | done | Bootstrap session |
| T0.4 | CLAUDE.md files, STATUS.md, `.claude/` | done | Bootstrap session |

## Phase 1 — Web in isolation (needs only Chrome)

| # | Task | State | Notes |
|---|---|---|---|
| T1.1 | Clock in plain HTML/JS | todo | Independent of T0.1 — can be done today |
| T1.2 | `mock.js` fixtures | todo | |
| TT.1 | Extract `format.js` + node:test | todo | Pairs with T1.2 |

## Phase 2 — Android skeleton

| # | Task | State | Notes |
|---|---|---|---|
| T2.1 | Minimal Gradle project in Java | todo | Needs T0.1 |
| T2.2 | WebView + WebViewAssetLoader | todo | 🏁 **Milestone A** — first sign of life |
| T2.3 | Keep screen on, landscape, immersive | todo | |
| T2.4 | MIUI smoke test: autostart, battery, reboot | todo | Deliberately early. Riskiest unknown |

## Phase 3 — Python server (parallel with phase 2)

| # | Task | State | Notes |
|---|---|---|---|
| T3.1 | `/ping` | todo | Independent of T0.1 |
| T3.2 | Config loading | todo | |
| T3.3 | `/quotes` proxy | todo | ⚠️ Subtask 0: confirm brapi FX and crypto endpoints |
| T3.4 | `/weather` proxy | todo | |
| T3.5 | Scheduled Task, firewall, static IP | todo | Acceptance must be tested from the LAN |
| T3.6 | Serve the APK at `/app` | todo | |
| T3.7 | `POST /action/{id}` stub returning 501 | todo | v2 placeholder |
| TT.2 | Server unit tests + fixtures | todo | Pairs with T3.3, T3.4 |
| TT.3 | Two HTTP integration tests on port 0 | todo | |
| TT.4 | Contract tests, opt-in | todo | |

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
| T7.1 | Release keystore and signing | todo | Do this early — mixing keys forces an uninstall |
| T7.2 | Wireless adb from the container | todo | May fall back to host platform-tools |
| T7.3 | Pre-public review: secrets, README, screenshots | todo | Before flipping the repo public |
| TT.8 | `e2e/run_e2e.py`, five scenarios | todo | Needs TT.6 |
| TT.9 | CI workflow | todo | |

## Shortest path to seeing something work

`T0.1 → T1.1 → T2.1 → T2.2` puts a running clock on the phone. No network, no server, no MIUI
hardening — it validates the container, Gradle, `WebViewAssetLoader` and rendering in one go.

Then `T3.1 → T3.5 → T4.1 → T4.2 → T4.3` delivers the actual product behaviour. Quotes and
weather come afterwards; they are the least risky part and the easiest to defer.

## Open questions

- **brapi FX and crypto endpoints are unconfirmed.** Resolved as subtask 0 of T3.3. Fallbacks
  without a key: Binance public API for crypto, AwesomeAPI for FX.
- **adb from inside the container is undocumented.** Resolved in T7.2. Fallback is
  `tools/platform-tools/` on the host.
- **Whether MIUI wakes the screen reliably** decides whether ADR 0005 keeps its primary design
  or falls back. Resolved in T4.4.
