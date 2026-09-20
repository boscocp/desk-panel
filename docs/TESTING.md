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

The four browser checks under `e2e/layout/` are **not** in `make check` and not in CI: they
need Firefox on `PATH`, which is a host dependency neither of those can assume. They are run
by the acceptance of the tasks that own them, and by hand after anything that moves markup.
See the section below.

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

## The panel, in a real browser — `e2e/layout/`

Four checks, one harness. They drive Firefox over Marionette (its built-in automation
protocol — no driver binary, no npm, standard library only) at **872x392**, the phone's real
landscape viewport, and none of them needs the phone. `e2e/layout/README.md` is the long
version; this is what each one is for.

| | asks |
|---|---|
| `check_layout.py` | does every section fit, does anything clip, is anything drawn on top of anything else |
| `check_blackout.py` | does the panel go dark on both causes, hold what arrives, and draw it on the way back |
| `check_scroll.py` | does an overflowing card keep moving across a refresh |
| `check_pulse.py` | does a value pulse only when it changed |

All four take `--theme NAME`. Run `check_layout` and `check_blackout` for every theme;
`check_scroll` for a theme that answers overflow with motion, and `check_pulse` for one that
marks a changed value — both are optional in the theme contract (`docs/THEMING.md`).

Three things are worth knowing before trusting one. The first is true of all four; the other
two are `check_layout.py` alone, which is the only one of them that measures *where* anything
is:

- **The viewport is calibrated, not requested.** `SetWindowRect` sizes the outer window, and
  asking for 872x392 gave an `innerHeight` of 306 on the machine this was written on — 86px
  short, and wrong in the direction that looks like a pass. The harness measures what it got
  and refuses to run if it cannot converge.
- **`check_layout.py` measures each pass at every burn-in position.** The panel shifts a few
  pixels every four minutes (T6.2), so measuring it once means checking the worst position one
  run in seven, which is a check that fails on a Tuesday.
- **`check_layout.py` pins the page's clock** to do that. Otherwise the panel puts itself back
  where the wall clock says a moment after the harness moves it — and the stress pass rendered
  *today's* pt-BR date, so "the widest case" was only the widest case on the days it happened
  to be.

  The other three freeze the page's timers instead, which is a weaker and sufficient
  guarantee: none of them reads an absolute position, so the panel is free to be wherever the
  shift last put it. `check_scroll.py` reads the scrolling box's *own* transform, which an
  ancestor's does not enter into.

What none of them can tell you is whether the panel is *readable*. Nothing here measures
contrast, glow or type against a human at 50cm, and Android resolves `sans-serif-condensed` to
Roboto Condensed while the host falls back to something wider — so text widths here are a
conservative estimate, never the truth.

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
`screen=wake|sleep`, `screen=thermal|thermal-clear`, `night=on|off`, `dormant=on|off` — fire
only when something changes; a
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
| 8 | `dumpsys battery set temp 460` while online | `screen=thermal` within 15s |
| 9 | `dumpsys battery set temp 300` while blanked | `screen=thermal-clear` within 15s, `mWakefulness=Awake` |

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
- **`screen=thermal` is a prefix of `screen=thermal-clear`**, so `grep -q 'screen=thermal'`
  matches the line that says the panel came *back*. Every assertion about blanking anchors the
  end of the line — `grep -qE 'screen=thermal$'` — and `MarkersTest` asserts the collision
  exists so nobody rediscovers it from a test that passed for the wrong reason (T5.5).
- **`screen=thermal` reports why the panel *you are looking at* is dark**, not what the
  temperature did. It is the conjunction of the thermal verdict and the PC's: crossing 45
  degrees with the PC already away emits nothing, because the display is out and heat took
  nothing off it, and the marker then fires at the *login* that brings the panel up black. Its
  falling edge has two causes and the line beside it says which: alone it means the device
  cooled, paired with `screen=sleep` it means the PC left and now owns the dark.
- `screen=thermal` is **not** `screen=sleep` with a different name. Sleep releases
  `FLAG_KEEP_SCREEN_ON` and hands the display to Android, to be woken from outside; thermal
  keeps the Activity foreground at `screenBrightness = 0f` precisely so it is still running to
  notice the device cooling. A test that asserts `mWakefulness` went to `Dozing` is asserting
  against the wrong mechanism — while blanked the device is `Awake` and that is correct
  ([ADR 0012](adr/0012-thermal-screen-cutoff.md)).
- `dumpsys battery set temp` **sticks until `reset`**, across app restarts and reboots. A
  forgotten injection looks exactly like a real thermal problem, and the panel will sit black
  with the PC plainly on.
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
- The glow reads as light rather than as a smudge, on the real AMOLED at the real font — the
  browser harness measures geometry and falls back to a wider typeface (T6.2).
- The host is still clean: no Android SDK in `%LOCALAPPDATA%`, `java -version` still fails.
- The app returns to the foreground on its own after a phone reboot.
