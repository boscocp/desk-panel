# Testing

Every acceptance criterion is a command with an exit code. Nothing in this project is verified
by looking at output and deciding it seems fine — if a task cannot be checked by a command, the
task file is wrong.

**Five layers.** Three use standard library tooling and install nothing: the server
(`unittest`), the web layer (`node:test`) and the end-to-end suite (Python + adb). The two
Android layers do take a test dependency — JUnit for the JVM tests, Espresso for the
instrumented ones — because the platform ships no alternative. Nothing is installed on the
host for them; they resolve inside the container.

## Running

```bash
make check                                       # everything that needs no phone
make test-server                                 # python -m unittest discover -s server/tests -t .
make test-web                                    # node --test "web/test/**/*.test.js"
make test-android                                # ./gradlew test, in the container
make connected                                   # Espresso, needs the phone
make e2e                                         # python e2e/run_e2e.py
make contract                                    # hits the real APIs, opt-in
```

`make check` is what agents call. **CI does not call it** — `.github/workflows/ci.yml` invokes
`python -m unittest`, `node --test` and `./gradlew` directly, because the Android job has no
Docker. That divergence is deliberate and TT.9 owns keeping the two in step; `check_workflow.py`
asserts the commands match.

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

Two kinds, defined in `Markers.java` (TT.6). **Transitions** — `state=online|offline`,
`screen=wake|sleep`, `night=on|off`, `dormant=on|off` — fire only when something changes; a
steady state logs nothing, and T4.2 asserts exactly that. **Heartbeats** — `tick=`, `ping=`,
`data=ok|err`, `battery=` — fire per cycle at a bounded rate, because "still running" and "at
most four polls a minute" cannot be asserted any other way.

**This table is the source.** `e2e/README.md` and `tasks/TT.8-e2e-suite.md` link here rather
than restating it — three copies had already drifted apart on scenario 5.

| # | Action | Assertion |
|---|---|---|
| 1 | Server up | `state=online` within 5s |
| 2 | Kill the server | `state=offline` and `screen=sleep` within 20s (backoff allowed for) |
| 3 | Start the server | `state=online` and `screen=wake` within 20s |
| 4 | `/quotes` serving a known fixture | Rendered values match, via Espresso-Web |
| 5 | Phone Wi-Fi off for 30s | No crash in logcat; recovers unaided |
| 6 | `dumpsys battery unplug` while offline | `dormant=on`, then no `ping=` and no held wake lock |
| 7 | `dumpsys battery reset` while dormant | `dormant=off` and a `ping=` within 10s |

The 20s allowances exist because the offline backoff caps at 15s (T5.3). Tighter windows
produce flaky failures that are not bugs.

**Clear the buffer before changing the PC's state, never after.** `adb logcat -c` followed by
killing the server reads naturally and is a race: the app notices within one poll interval —
2s while online — so the clear usually lands after the transition and wipes the marker the
assertion is about. The run then fails in the most misleading way available, with an empty log
and an app that did everything right. Measured 2026-09-19; the same trap cost a session once
already, over `am start`.

Two more things the markers do not say, both worth knowing before writing an assertion against
them:

- `screen=sleep` means the app cleared `FLAG_KEEP_SCREEN_ON`, not that the panel went dark. The
  display goes out one device timeout later, and whether it is genuinely off is eyes-only
  (T4.4's manual check, [ADR 0014](adr/0014-poll-loop-outlives-the-screen.md)).
- `ping=ok|err` is one line per probe, so counting it over a window measures the *cadence*, not
  the health: 2s while online, and 2/4/8/15/15 climbing to the cap while offline. A minute
  measured from the moment the PC goes away holds seven, a settled offline minute holds four.
  Give the ladder twenty seconds to finish climbing before asserting a count (T5.3).
- `dormant=on` is the log saying its own silence is deliberate (T5.6). Offline and on battery
  the app hands its schedule to `AlarmManager` and goes quiet for fifteen to twenty-six minutes
  at a time — the alarm is inexact and the platform widens it — so
  **an assertion that counts `ping=` over a window has to know which power state it is in** —
  the same window is four lines on mains and zero on battery. `dumpsys battery unplug` and
  `reset` put the device in either state on demand, and fire the real power broadcasts.
- `battery=` is one line per broadcast, which on this device is about every eight seconds while
  charging. It is **not** one line per render: the page is only re-rendered when the level or
  the temperature actually changes, so the marker count and the render count differ on purpose
  (T5.4).
- `panel=rendered` is **not** once per session. The wake relaunches the Activity, so one lands
  about a second after each `screen=wake`, and WebView is entitled to fire `onPageFinished`
  twice for a single load — both have been seen on the device. Assert that it appears, never
  how many times.

Scenario 5 may need permissions MIUI withholds. If it does, it is marked manual rather than
deleted — the scenario is real, the automation is what is missing.

## Contract tests

A few tests hit brapi and Open-Meteo for real, to catch upstream schema drift. They are guarded
by `unittest.skipUnless` on `RUN_CONTRACT_TESTS` and never run in normal CI.

## What is not automated

Some things no script can judge, listed here so they are not forgotten:

- The offline state genuinely looks off in a dark room.
- Text is legible from about 50 cm.
- The host is still clean: no Android SDK in `%LOCALAPPDATA%`, `java -version` still fails.
- The app returns to the foreground on its own after a phone reboot.
