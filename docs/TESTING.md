# Testing

Every acceptance criterion is a command with an exit code. Nothing in this project is verified
by looking at output and deciding it seems fine — if a task cannot be checked by a command, the
task file is wrong.

All four layers use standard library tooling. No test dependency is installed anywhere.

## Running

```bash
make check                                       # everything that needs no phone
make test-server                                 # python -m unittest discover -s server/tests -t .
make test-web                                    # node --test "web/test/**/*.test.js"
make test-android                                # ./gradlew test, in the container
./gradlew connectedAndroidTest                   # Espresso, needs the phone
make e2e                                         # python e2e/run_e2e.py
make contract                                    # hits the real APIs, opt-in
```

`make check` is what CI and agents call.

## Server — `unittest`

Python documents no supported way to drive a `BaseHTTPRequestHandler` without a socket. Rather
than improvise one, the handler stays dumb and all real logic — config loading, provider
response normalisation, payload assembly — lives in plain functions the tests call directly.

Two integration tests bind an `HTTPServer` on port 0 to cover the actual HTTP path.

Outbound calls are patched with `unittest.mock`; responses come from recorded fixtures in
`server/tests/fixtures/`. **Unit tests never touch the network.**

## Web — `node:test`

Node's built-in runner, stable since Node 20, with `node:assert`. No jsdom, therefore no DOM:
`web/js/format.js` holds the pure functions (currency, percent change, WMO weather code to
label, up/down colour) and that is what gets tested. DOM code stays thin enough not to need
tests.

## Android — JVM and instrumented

`src/test/` runs on the JVM via `./gradlew test`: fast, no device, and it covers `PcState.java`
— the online/offline machine and the backoff schedule, written with no Android imports
precisely so it can be tested here.

`src/androidTest/` runs on the real phone via `./gradlew connectedAndroidTest`, using Espresso
and Espresso-Web to assert on values rendered inside the WebView. This does not run in CI.

## End-to-end

`e2e/run_e2e.py` drives the real device over adb.

It deliberately **does not read screen state from the OS**. `dumpsys power` and `mWakefulness`
are not in Android's public documentation — they are known from AOSP source and can change
without notice. Instead the app emits its own markers on the `DeskPanel` logcat tag, and the
suite asserts on those. `dumpsys power` is consulted only as an optional corroborating check
that warns rather than fails. Full reasoning in [ADR 0009](adr/0009-testing-strategy.md).

Those markers are a contract. Renaming one breaks the suite.

| # | Action | Assertion |
|---|---|---|
| 1 | Server up | `state=online` within 5s |
| 2 | Kill the server | `state=offline` and `screen=sleep` within 20s (backoff allowed for) |
| 3 | Start the server | `state=online` and `screen=wake` within 20s |
| 4 | `/quotes` serving a known fixture | Rendered values match, via Espresso-Web |
| 5 | Phone Wi-Fi off for 30s | No crash in logcat; recovers unaided |

## Contract tests

A few tests hit brapi and Open-Meteo for real, to catch upstream schema drift. They are guarded
by `unittest.skipUnless` on `RUN_CONTRACT_TESTS` and never run in normal CI.

## What is not automated

Some things no script can judge, listed here so they are not forgotten:

- The offline state genuinely looks off in a dark room.
- Text is legible from about 50 cm.
- The host is still clean: no Android SDK in `%LOCALAPPDATA%`, `java -version` still fails.
- The app returns to the foreground on its own after a phone reboot.
