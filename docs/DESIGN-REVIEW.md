# Design review: the seams, before strangers arrive

**2026-09-27, wave 30, [T7.9](../tasks/T7.9-seams-review-before-strangers.md).** One pass over
the whole codebase asking a single question: **where will a contributor who did not write this
put their change in the wrong file?**

It is deliberately run *after* [CONTRIBUTING.md](../CONTRIBUTING.md), which states the rules this
repository claims to follow. Without that page this would have been one person's taste; with it,
every finding below is the same shape — *the guide says X, here is where the code makes X hard*.

Not a pattern hunt. Nothing here proposes a framework, a container or a vocabulary; three of the
four layers already do dependency inversion, in plain constructor arguments and plain function
tables, and the recommendations are to **apply the pattern this project already has** in the one
place that does not.

## Method

Read in four passes — `web/`, `server/`, `android/`, and the harness under `scripts/` and `e2e/`
— and then four **contributor walks**: the plausible first contributions, each traced file by
file. The walks are where the findings came from; the reading only explained them.

## What the layers are

| Layer | Size | Units | How it is tested |
|---|---|---|---|
| `web/` | ~2,100 lines | `format.js` (pure), `host.js` (the theme registry), `app.js` (the native seam), two themes | `node:test` over pure functions; six browser checks under `e2e/layout/` |
| `server/` | ~5,000 lines | `App` (caches and payload), `Handler` (routing only), five provider modules, `actions.py`, `verify_login_scope.py` | `unittest`, network patched, fixtures committed |
| `android/` | ~3,800 lines | `MainActivity`, `PanelService`, two pollers, and six plain classes holding the decisions | `./gradlew test` on the JVM; the plain classes are why that is possible |
| harness | — | seven `scripts/check_*.py`, six browser checks, `run_e2e.py` | each script carries its own `--self-test` |

## The three seams this project already gets right

These are the yardstick for everything below, and a contributor should be shown them first.

- **`server/actions.py` injects `runner` and `which`.** Every test asserts on an argument list
  without a mixer, a desktop session or a subprocess. That is dependency inversion with no
  vocabulary attached, and it is why the action tests can assert that a refused id runs *nothing
  at all* — a status-only test could not tell 404-before-spawning from 404-after.
- **`web/js/host.js` is a registry.** `DeskPanel.defineTheme(name, api)` and `useTheme(name)`;
  a theme is a directory and two lines in `index.html`. The core knows no theme's name.
- **The Android decisions live outside Android.** `PcState`, `ThermalState`, `NightWindow`,
  `BatteryReading`, `Actions` are plain Java with no Android imports, which is why the rules they
  hold are covered by `./gradlew test` with no device. `PanelService` is 1,154 lines and holds
  almost no decision: the dormancy *rule* is `PcState.DORMANT_ALARM_MS` and `PcPoller`; the
  service only makes the platform calls.

## The four walks

| A contributor wants to… | Files touched | Verdict |
|---|---|---|
| Add a theme | a new directory, 2 lines in `web/index.html` | **Good.** The registry does its job |
| Add an action (a third button) | `server/actions.py`, `Actions.java`, `format.js`, `config.toml` | **Deliberate.** Three of the four are defence in depth (ADR 0015) — but nothing checks the lists agree |
| Add a market (a fourth row of prices) | a new `providers_*.py`, **four separate places in `server/server.py`**, `mock.js`, `DataPayload.java`, `format.js`, a theme | **The finding.** See F1 and F2 |
| Add a second weather provider | `App.weather()`, by editing it | **No seam at all.** See F2 |

The last row is the question [T7.9](../tasks/T7.9-seams-review-before-strangers.md)'s manual
check asks a stranger, and the honest answer today is "you would edit the method": weather is
reached by four direct calls into `providers_openmeteo` from inside `App.weather()`, so a second
provider is an `if` in a method, not a new file that gets registered.

## F1 — The payload shape is written down four times and cross-checked zero times

**The evidence is not hypothetical.** `DataPayload.merge` rebuilds the payload key by key on its
way into the WebView, so a key nobody names there does not reach the phone — with a correct
server and a correct page. That shipped **twice**: `night` in T6.4 and `actions` in T8.2, two
waves apart, the second time with a comment in the file warning about the first.

The shape currently exists in four places, none of which can see the others:

1. `web/js/mock.js` — what a browser-only contributor develops against.
2. `App.quotes()` / `App.weather()` — what the PC actually sends.
3. `DataPayload.merge` — what reaches the page on the phone.
4. `DataPayloadTest.QUOTES` — a string literal, the test's own fourth copy.

**T7.9 asks this task to decide whether a comment is the best available, and it is not.** The
comment has now failed once, *in the file it is written in*, which is the strongest evidence a
comment can produce about itself. What is missing is not a schema language or a code generator —
both would be a dependency and a build step this project refuses. It is **one committed fixture**
plus one assertion per layer: the server test writes the fixture from its own payload assembly,
the web test feeds it to the page's reader, and the Android JVM test reads the same file and
asserts `merge` preserves every top-level key of it. Adding a key server-side then turns the
Android test red at the point of the change.

Feasible without a new dependency: `android/app/build.gradle.kts` already points `assets.srcDirs`
at `web/`, so pointing test resources at a fixtures directory is a move the file already makes.

Filed as **T10.1**. The same mechanism covers the second instance of this class — the action id
that lives in `actions.CATALOGUE`, `Actions.ALLOWED` and `format.js`'s `words.actions`, three
lists that nothing compares.

## F2 — The server has a catalogue pattern and the providers do not use it

`actions.py` holds a table: id → platform → argument list, with the code reading the table rather
than branching. Twelve lines away, the same module's `describe()`, `run_action()` and the 501
path all read that one table and needed no changes when the microphone press became four
commands.

The providers are the opposite. Adding a market means editing `server/server.py` in four places:

- `producers` in `App.quotes()` — the fetch,
- `wanted` in `App.quotes()` — the expected row count, for the partial-market badge,
- `_history_producer()` — an `if/elif/else` chain on the market name,
- `key_for()` — which field identifies a row, with FX as the exception.

None of those four is near the others, and a contributor who finds three of them gets a market
that renders and has no sparkline, or one whose stale badge never fires. The five provider
modules also have five different call shapes (`load(symbols)`, `load(symbols, token,
per_request)`, `fetch_geocode`/`normalise_geocode`/`fetch_forecast`/`normalise`,
`moon_phase`/`synodic_phase`), so there is no shape to conform to even if you wanted to.

The fix is the table this codebase already writes elsewhere — one `MARKETS` entry per market
carrying the loader, the history loader, the config key and the row key — and **not** a provider
base class or a plugin system. Filed as **T10.2**, with the weather seam as its second step,
because a second weather provider is the walk with the worst answer today.

## F3 — A 97-case self-test that nothing runs

`server/verify_login_scope.py` carries a `--self-test` with **97 cases**, covering the parsers for
all three operating systems from fixtures — which is the only way macOS is checkable at all from
this desk. `make lint-selftests` discovers self-tests by `grep -l '"--self-test"' scripts/*.py`,
and that glob stops at `scripts/`.

So the file exists, the cases pass today (verified while writing this: 97/97), and **nothing
would say so if they stopped**. This is TT.12's exact subject — a self-test with no runner —
surviving the wave that was written to end it, because the fix was a glob over one directory and
the repository has checkable code in two. Wave 25's note recorded the gap and nothing turned it
into a command with an exit code.

Filed as **T10.3**, and it is the smallest task in the repository: a second glob.

## Where tests are hard to write, and what that says

The repository's test discipline is strong enough that the gaps are informative rather than
embarrassing:

- **`PanelService` and `MainActivity` have no unit tests**, and should not. Every decision they
  used to hold has been moved out to a plain class; what is left is Android API calls, which is
  what the instrumented tests and the E2E markers are for (ADR 0009). This is the design working.
- **`App.quotes()` is tested through its caches**, not directly, because it is where the four
  branch points of F2 live. The difficulty *is* the finding.
- **Nothing tests `mock.js`.** It is the entry point for the tier of contributor the project most
  wants, and it is the copy of the payload contract nobody asserts anything about (F1).
- **`e2e/layout/` needs a browser and is not in `make check`.** That is deliberate and documented,
  and the six checks are individually mutation-tested, which is a stronger discipline than most
  of what `make check` runs.

## What is deliberately left alone

Half the value of this document for a newcomer is knowing which oddities are load-bearing. Each
of these looks like a finding, was examined, and is staying:

- **Java, not Kotlin** ([ADR 0001](adr/0001-java-over-kotlin.md)). One Activity and six plain
  classes; the Kotlin plugin would add a toolchain to a project whose whole Android story is
  "nothing on the host".
- **No framework in `web/`** ([ADR 0006](adr/0006-no-framework-web-layer.md)). The file you open
  in a browser is the file that ships. A bundler would end that, and it is the property the first
  tier of [RUNNING-LOCALLY.md](RUNNING-LOCALLY.md) is built on.
- **Standard library only in `server/`.** It is launched by the login itself and has to run on a
  clean box. This is also why there is no schema library in F1's recommendation.
- **The action id in three lists.** ADR 0015 wants the phone's allowlist to be independent of the
  server's, so a compromised asset cannot widen what the bridge will send. The duplication is the
  defence; only the *absence of a check that they agree* is a finding, and it rides with T10.1.
- **`PanelService` at 1,154 lines.** Long, and almost all of it is platform calls and the
  javadoc explaining which of them are ordered and why. Splitting it would move the ordering
  problem across a file boundary without making it testable.
- **`Handler` is dumb on purpose.** Python documents no way to exercise a
  `BaseHTTPRequestHandler` without a socket, so routing and serialising is all it does.
- **`config.example.toml` is the configuration documentation.** A second page describing the
  same keys is a second page that goes stale.
- **`SharedPreferences`, no database.** The panel persists almost nothing; a database would be a
  migration story for two values.

One item found while reading that belongs to somebody else: **`WINDOWS-NEXT-SESSION.md` is
tracked at the repository root** and is a session hand-off note, not documentation. That is
[T7.3](../tasks/T7.3-pre-public-review.md)'s pre-public pass, not a design finding, and it is
named here so it is not lost.

## What this review did not do

It changed no code. Three task files were written and three rows added to `tasks/STATUS.md`;
every recommendation above is a task with an acceptance command, not a diff. A review that also
rewrites is a review nobody can check.

It also did not read the four layers evenly: the walks pushed almost all of the attention into
`server/` and the `web/`↔`android/` seam, because that is where the walks went. `format.js` at
1,068 lines and `e2e/layout/`'s six checks were read for shape and not adversarially. If a second
pass ever happens, start there.
