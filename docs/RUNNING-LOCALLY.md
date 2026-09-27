# Running it locally

From `git clone` to something moving on screen, for someone with **no Redmi, no Windows PC and
no model writing the commands**. The repository answers this in pieces elsewhere —
[BUILD.md](BUILD.md) for the APK, [TESTING.md](TESTING.md) for the suites,
[SERVER-SETUP.md](SERVER-SETUP.md) for the PC half — and nowhere from the top. This is from the
top.

It is organised by **what you own**, not by what the project contains. Stop at the tier where
you run out of hardware; each one is useful on its own, and the first needs nothing at all.

Versions and floors are in [REQUIREMENTS.md](REQUIREMENTS.md). Nothing below installs a
dependency, because there are none to install.

---

## Tier 1 — the panel in a browser

**You need:** a browser. That is the whole list.

```bash
git clone <this repo>
cd desk-panel
```

Open `web/index.html` — double-click it, or:

```bash
xdg-open web/index.html      # Linux
open web/index.html          # macOS
start web\index.html         # Windows
```

**What you should see:** the panel, in a cyberpunk-neon skin, with a ticking clock and rows of
quotes, crypto and weather that change every few seconds. All of it is fake.

`web/js/mock.js` feeds the page the exact payload shape production sends, and it decides whether
to do so by looking at `location.protocol`: from `file:` it is the data source, and inside the
APK — which serves the page from `https://appassets.androidplatform.net/` — it is inert. So the
file you just opened is the same file that ships, with no build step and no development mode
([ADR 0006](adr/0006-no-framework-web-layer.md)).

**This is where most of the interesting surface is.** The layout, the themes, the sparklines, the
burn-in shift, the night profile: all of it is `web/`, and all of it can be changed and reviewed
with nothing but this. Edit a file, reload the page.

### The tests for it

**You need:** Node (see [REQUIREMENTS.md](REQUIREMENTS.md)).

```bash
make test-web
```

They are `node:test` against pure functions in `web/js/format.js`, which is why they need no
browser and run in under a second. **That purity is a rule, not a happy accident** —
[CONTRIBUTING.md](../CONTRIBUTING.md) explains why, and a formatting change that needs a DOM to
test is a sign the logic is in the wrong file.

---

## Tier 2 — plus the server, with real data

**You need:** Python (see [REQUIREMENTS.md](REQUIREMENTS.md)). Standard library only, so there is
nothing to install beyond Python itself — no virtualenv, no `pip install`.

```bash
cp server/config.example.toml server/config.toml
python server/server.py
```

**What you should see:** a few lines naming the port, the tickers, the city and which actions are
enabled, and then request lines as they arrive. Leave it running and visit
<http://127.0.0.1:8777/quotes> in a browser.

`config.example.toml` is the documentation for the configuration — every key, its default and the
values that actually work, in the file itself. Weather needs no credential. Quotes want a free
token from the provider named in that file; without one, that route answers with what it can and
the panel shows the rows as stale rather than pretending.

**The server is not a web server for the panel.** It is the PC's *login signal* — the phone
decides the PC is awake because this process answers, which is why it is started by the graphical
session and dies with it ([ADR 0004](adr/0004-server-is-login-signal-and-proxy.md),
[ADR 0010](adr/0010-login-signal-is-session-scoped.md)). Do not put it in a container or a system
service: it would answer without a login and report the wrong thing.

### Its tests

```bash
make test-server
```

No network: the outbound calls are patched and the fixtures are in `server/tests/fixtures/`. The
contract tests that do call the real upstreams are opt-in and skipped unless you ask for them —
`make contract`.

---

## Tier 3 — the full rig

**You need hardware from here on:** Docker for the Android toolchain, an Android phone on `adb`,
and the PC and the phone on the same LAN.

Say plainly what this buys and what it costs: **a contributor without any of it can still have a
completely green `make check`**, and can change everything in `web/` and `server/`. What needs
the phone is the panel's behaviour on a real screen, and nothing else.

```bash
make apk        # the debug APK, built inside the container
```

Nothing lands on the host — no JDK, no Android SDK, no Android Studio
([ADR 0003](adr/0003-containerized-toolchain.md)). The first run downloads the image and takes a
few minutes; after that it is seconds.

Then:

- [PHONE-SETUP.md](PHONE-SETUP.md) — what Android has to be told, and how to verify each grant.
- [INSTALL-PHONE.md](INSTALL-PHONE.md) — the same switches on the one phone this was built for.
- [SERVER-SETUP.md](SERVER-SETUP.md) — making the server start with the graphical session on
  Windows, Linux or macOS, plus the firewall rule and the static address.

---

## The one command to know

```bash
make check
```

Everything that needs no phone: the guards, the server suite, the web suite and the Android JVM
tests. It is what CI runs, command for command — `scripts/check_workflow.py` fails the build if
the two ever drift — so a green `make check` here means a green CI there.

`make` on its own lists every target with a line of explanation.

**Use the targets, not the long forms.** The long commands are in `docs/TESTING.md` for when you
need to run one suite in isolation, but a tutorial that teaches them teaches something the
repository is free to change without telling you.

## When something does not work

| Symptom | Where to look |
|---|---|
| `make check` fails on `lint-*` | One of the repository's own guards; each prints what disagreed and with what |
| `make check` fails on Docker | You are missing Docker. `make test-web` and `make test-server` are the useful subset without it |
| The panel in the browser is blank | The browser is refusing `file:` — some builds block local scripts. Try another browser first: serving the directory (`python -m http.server -d web`) loads the page but **not the mock data**, because `mock.js` feeds it only from `file:` |
| Quotes are stale in tier 2 | No token in `server/config.toml`, which is the expected state on a clean clone |
| The panel says offline with the server running | The APK pins one PC address at build time; see [PHONE-SETUP.md](PHONE-SETUP.md) |

## What to read next

- [ARCHITECTURE.md](ARCHITECTURE.md) — the full picture and the three invariants. Read this
  before changing anything that crosses a layer.
- [CONTRIBUTING.md](../CONTRIBUTING.md) — why the code is laid out this way and what will send a
  pull request back.
- [adr/](adr/) — the decisions, including the options that were rejected and on what evidence.

`CLAUDE.md` files are instructions for agents working on this repository, not for you. Anything
in them a human needs belongs in the documents above; if you find something there that is not
here, that is a bug in this page.
