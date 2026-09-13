# 0009 — Zero-dependency testing; E2E asserts on app logs, not dumpsys

Status: accepted · 2026-09-13

## Context

Work happens one task per session, days apart, largely driven by an agent. For that to function,
every task must end in something that produces a pass or a fail on its own — not "open it and
see whether it looks right".

Two constraints shaped the result. The project refuses new dependencies, on the host and in the
repo. And the most important assertion in the whole suite — "is the phone's screen asleep?" —
turns out to have no documented answer.

## Decision

### Five layers

Three install nothing: server, web and end-to-end. The two Android layers take JUnit and
Espresso, which the platform gives no way around; both resolve inside the container, so the
host stays clean either way.

| Layer | Tool | Command |
|---|---|---|
| Server | `unittest` + `unittest.mock` | `python -m unittest discover -s server/tests -t .` |
| Web | `node:test` + `node:assert`, stable since Node 20 | `node --test "web/test/**/*.test.js"` |
| Android unit | JUnit on the JVM | `./gradlew test` |
| Android instrumented | Espresso, including Espresso-Web | `make connected` |
| End-to-end | Python + adb | `python e2e/run_e2e.py` |

### The E2E does not read screen state from the OS

The usual recipe is `adb shell dumpsys power` filtered for `mWakefulness`, and it is **not
documented** by Android — the field is known from reading AOSP source. `dumpsys display` and
`dumpsys window` are equally undocumented for this purpose. `screencap` is a documented command,
but what it returns with the screen off is not specified. `adb shell input keyevent` does not
appear in the official adb documentation at all; only the `KEYCODE_WAKEUP` constant is
documented.

Building the project's central assertion on undocumented, vendor-variable behaviour would mean
a suite that breaks on a MIUI update with no warning.

So the app reports its own state, via `Log.i` on the tag `DeskPanel`, emitting `state=online`,
`state=offline`, `screen=sleep` and `screen=wake`. `run_e2e.py` asserts on
`adb logcat -s DeskPanel`. This is fully under our control, documented by us, and survives OS
updates.

`dumpsys power` is still consulted as an **optional corroborating check**, isolated in one
function with a comment naming it as AOSP-derived. If it disagrees, the suite warns; it does
not fail.

### Contract tests are separate and opt-in

Unit tests never touch the network: outbound calls are patched and responses come from recorded
fixtures in `server/tests/fixtures/`. A handful of contract tests do hit brapi and Open-Meteo to
catch upstream schema drift, guarded by `unittest.skipUnless` on the `RUN_CONTRACT_TESTS`
environment variable.

Pact is the formal pattern here, but it is an external dependency for two endpoints. Not worth
it.

## Consequences

- The whole suite runs on a clean machine with Python and Node and nothing else.
- Test design pushed back on production design twice, and improved it both times: server logic
  moved out of the HTTP handler into pure functions, and web logic concentrated in
  `web/js/format.js`. Both were done because the test tools cannot reach the alternative.
- The logcat markers are now a **contract**. Renaming one breaks the E2E suite, which is why
  `android/CLAUDE.md` says so explicitly.
- `connectedAndroidTest` cannot run in CI — it needs the physical device — so it stays local.
- CI uses first-party GitHub actions (`setup-python`, `setup-node`, `setup-java` plus
  `gradle/actions/setup-gradle`). `android-actions/setup-android` is third-party and not
  GitHub-certified; worth knowing if it ever becomes necessary.

## References

- <https://docs.python.org/3/library/unittest.mock.html>
- <https://nodejs.org/api/test.html>
- <https://developer.android.com/training/testing/fundamentals>
- <https://developer.android.com/training/testing/espresso/web>
- <https://developer.android.com/tools/adb>
