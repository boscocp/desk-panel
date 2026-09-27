# What you need installed, and what you deliberately do not

This project's dependency list is nearly empty **on purpose**, and that is a constraint rather
than an accident of youth: no framework in `web/`, standard library only in `server/`, no build
step for the panel, and the entire Android toolchain inside a container so it never touches the
host ([ADR 0003](adr/0003-containerized-toolchain.md), [ADR 0006](adr/0006-no-framework-web-layer.md)).

A pull request that adds `requirements.txt`, a `package.json` or a JavaScript framework is a
**design change**, and [CONTRIBUTING.md](../CONTRIBUTING.md) says what it has to argue.

## The versions, and the file that decides each

`scripts/check_requirements.py` reads this table and the files beside it, and fails if they
disagree. **The build is the truth and this page follows it** — a bump in `docker/Dockerfile`
turns the guard red, which is the moment this page is cheapest to fix.

| What | Version | Decided in | Why this one |
|---|---|---|---|
| Python | 3.11 | `server/server.py` (`MIN_PYTHON`) | `tomllib` landed in 3.11 and the config is TOML. A floor, not a pin: 3.14 is what this desk runs |
| Python (CI) | 3.13 | `.github/workflows/ci.yml` | What the runners install. Above the floor on purpose, so "works on my machine" is never the floor's fault |
| Node | 24 | `.github/workflows/ci.yml` | Only for `node --test`, the built-in runner. There is no `package.json` to install from |
| JDK | 21.0.5 | `docker/Dockerfile` | The image is pinned by digest, so this is the compiler every build uses. Nothing is installed on the host |
| Java bytecode | 17 | `android/app/build.gradle.kts` | What the APK targets. A JDK 21 that emits 17 is deliberate — the toolchain moves, the artefact does not |
| Gradle | 9.7.1 | `android/gradle/wrapper/gradle-wrapper.properties` | The wrapper downloads it; you never install Gradle |
| compileSdk | 36 | `android/app/build.gradle.kts` | Compile against the newest, run on the oldest supported |
| minSdk | 26 | `android/app/build.gradle.kts` | `setShowWhenLocked` / `setTurnScreenOn` arrived in API 27 and the panel needs them; 26 is the floor for everything else and those two calls are guarded |
| Android build-tools | 36.0.0 | `docker/Dockerfile` | Inside the image only |
| Android platform | android-36 | `docker/Dockerfile` | Inside the image only |
| Command-line tools | 13114758 | `docker/Dockerfile` | The SDK installer's own build number. Pinned because "latest" is not a version |
| ruff | 0.16.9 | `.github/workflows/lint.yml` | Installed in the lint job and **never** in `server/`. A linter shipped with the server would break the rule it exists to keep |

## What you actually have to install

Depends entirely on which tier of [RUNNING-LOCALLY.md](RUNNING-LOCALLY.md) you want:

| Tier | Needs | Does not need |
|---|---|---|
| The panel in a browser | a browser | Python, Node, Docker, a phone |
| Plus the tests | Node 24, Python 3.11+ | Docker, a phone |
| Plus the PC server | the same | Docker, a phone |
| The APK | Docker | a JDK, an Android SDK, Android Studio |
| The phone | Docker, `adb`, an Android device | — |

`make check` — the repository's headline command — needs **Python, Node and Docker**, and no
phone. Without Docker, the two suites that matter most to a web or server contributor still run:
`make test-web` and `make test-server`.

## The dependency inventory, in full

Because it is short enough to list, and a list that fits on a screen is a list somebody will
notice growing.

- **`web/`** — nothing. No framework, no bundler, no `package.json`, no CSS preprocessor. The
  tests run in `node:test` against pure functions in `web/js/format.js`; the panel itself runs in
  a WebView with four scripts loaded by `index.html`.
- **`server/`** — the Python standard library, and that is the whole list. No `requests`, no
  Flask, no virtualenv. It has to run on a clean box with nothing installed, because it is
  launched by the login itself.
- **`android/`** — the Android Gradle Plugin and the platform SDK, both inside the container, and
  no third-party library in `app/build.gradle.kts`. The tests are JUnit and the panel is one
  Activity, one service and a WebView.
- **`e2e/`** — Python standard library plus `adb` on the host. The browser checks under
  `e2e/layout/` drive Chrome through the DevTools protocol over a plain socket rather than
  through Selenium or Playwright, for exactly this reason.
- **CI** — `ruff`, pinned, and `shellcheck` and `PSScriptAnalyzer`, both preinstalled on the
  GitHub runner. None of them is needed to work on the project.
- **Two upstreams**, both reached by the PC and never by the phone: a quotes provider that wants
  a free token, and a weather provider that wants none. The token lives in `server/config.toml`
  on the PC and never enters git or the APK ([ADR 0013](adr/0013-local-configuration-boundaries.md)).

## If a floor is wrong for you

Say so in an issue with the version you have and what it did. The floors above are each one
sentence of justification long, and a floor that costs a contributor more than it buys the
project is worth arguing about — the Python one in particular has already moved once, from a
pin to a floor, because the development machine ran ahead of it.
