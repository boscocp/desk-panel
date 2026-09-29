# Contributing

This repository has an unusual property worth protecting: **it explains itself.** The comments
say *why* rather than *what*, the decision records under [docs/adr/](docs/adr/) keep the options
that were rejected and the evidence that rejected them, and every commit has a task file behind
it carrying the reasoning that produced it.

That survives exactly as long as the next person understands it is the point. So this is not a
style guide with an opinion about braces — the mechanical parts are automated below so nobody
has to enforce them by hand. It is an argument about maintenance.

## What this project accepts

Thirty seconds, so you know whether your idea belongs here before you spend an evening on it:

- **Device reports, from anybody.** Did the screen really sleep and wake on your phone, did it
  survive a night on battery? The [device report](.github/ISSUE_TEMPLATE/device-report.yml)
  template asks the right questions. This is the contribution the project needs most, because it
  runs on one phone.
- **Bug reports, from anybody**, with the four fields the bug template asks for.
- **Themes and layouts.** `web/` is the natural place to contribute, and it runs in a browser with
  nothing installed.
- **New data providers**, behind the existing normaliser shape in `server/providers_*.py`.
- **Anything touching the three invariants in the README needs an ADR first**, then a PR. An ADR
  is not a hurdle; it is where the conversation happens. The `needs-adr` label marks those issues.

What it does not accept: authentication, cloud services, a framework in `web/`, or a dependency
in `server/`. Each is a decision recorded in `docs/adr/`, not an oversight. And this is one person
with one device: a good PR that cannot be verified without hardware may wait for a device report.

Start at [docs/RUNNING-LOCALLY.md](docs/RUNNING-LOCALLY.md) if you have not run anything yet. The
first tier needs no Python, no Node, no Docker and no phone.

For *where a change lands* — which seams are registries, which are four scattered edits, and
which oddities are load-bearing and should be left alone —
[docs/DESIGN-REVIEW.md](docs/DESIGN-REVIEW.md) walks four plausible first contributions file by
file.

## Keeping the code readable

### Comments carry the why

A comment that restates the code is noise. A comment explaining why the obvious thing was wrong
is what stops the bug coming back — and this project has the receipts: every one of the
following was written *after* paying for the lesson.

Read these before writing your first comment here; they are the teaching material:

- `BatteryReading.ABSENT` in `android/app/src/main/java/dev/bosco/deskpanel/` — why `-1` was the
  wrong sentinel, in the file where somebody would otherwise reintroduce it.
- `DataPayload.merge` — *"This copy is the whole of the wiring, and forgetting it is silent."*
  The same bug shipped twice, two waves apart, and the comment names both occurrences.
- `server/actions.py` — why the Windows COM interface declares eleven placeholder methods
  before `SetMute`, which is the difference between muting the speakers and setting a channel
  volume.

The test: **delete the comment and ask what a reader loses.** If the answer is "nothing, the
code says that", delete it for real.

### Logic stays out of Android classes

Anything with a decision in it belongs in a plain class that a JVM test can construct —
`PcState` and `ThermalState` are the pattern. An `Activity` or a `View` with a rule inside it can
only be tested on a device, and a test that needs a device is a test that does not run.
[ARCHITECTURE.md](docs/ARCHITECTURE.md) draws the boundary: the service owns the loop, `PcState`
owns the transitions, and `MainActivity` only does what it is told.

### `web/js/format.js` is pure functions only

No DOM, no timers, no globals. That is why the web tests need no browser and finish in under a
second. If a formatting change seems to need a DOM to test, the logic has landed in the wrong
file — move it here and the test gets easy.

### The three invariants are not open for casual change

They are stated in the [README](README.md) and argued in the ADRs: JavaScript never calls
`fetch`, the PC server is the login signal and is scoped to a graphical session, and screen state
follows the PC rather than a timeout.

A pull request that breaks one is **not wrong by definition** — but it needs an ADR making the
case, not a diff that quietly changes the behaviour. Two of the three have already been
re-argued once each; that is what the records are for.

### No new dependency without an argument

`web/` has no framework and no build step. `server/` is the Python standard library and nothing
else, because it has to run on a clean box. The Android toolchain lives only inside the
container. See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) for the full inventory and why it is
this short.

A PR that adds `requirements.txt`, a `package.json` or a framework is a **design change** and
should read as one: what it buys, what it costs the "clone and run" promise, and why the standard
library is not enough.

### A decision worth arguing about gets an ADR

Numbered, in [docs/adr/](docs/adr/), with the alternatives it rejected and the evidence.
[ADR 0010](docs/adr/0010-login-signal-is-session-scoped.md) and
[ADR 0014](docs/adr/0014-poll-loop-outlives-the-screen.md) are the models: both record reasoning
a reader six months later would otherwise have to reconstruct from a diff.

Copy the shape of an existing one — Context, Decision, Consequences, References. An ADR that
lists no rejected option is usually a decision nobody actually made.

## Commits

Conventional commits, in English, imperative mood:

```
feat: two buttons under the clock, and a tap the page cannot make itself
fix(server): the direction came from a device the press never touches
docs: wave 27 in the record, and the Files line that would have caught its bug
```

Types: `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `ci`. The subject says what changed;
the body says **why**, whenever the subject cannot. Long bodies are normal here.

`scripts/check_commit_msg.py` decides, and it checks **shape, never content**: a known type, at
most 80 characters, no trailing full stop, not Title Case, and a blank second line. Install the
hook so it runs before the commit rather than in CI:

```bash
make hooks        # git config core.hooksPath .githooks
```

**No attribution trailers.** This project's history carries one author; `Co-Authored-By:` lines
and tooling bylines do not belong in it, and the checker rejects them.

## Pull requests

Use the template — it is the shape the pull requests here already take, and the two fields that
matter most are the unusual ones:

- **Verified on the device, versus reasoned about.** This project runs on one phone and one desk.
  Saying which of the two a change is costs you nothing and is the single most useful line in the
  request. A fully green suite has shipped a completely dead button here before.
- **What was deliberately left out.** Every wave in this repository has had one.

**Reviews land before the merge, not after.** That is how every change here has gone in: open the
pull request, a review reads the whole diff, the findings are applied on the same branch, and
then it merges. Expect a round trip and read it as the normal path rather than as rejection —
recent reviews have caught a button that was silently dead in two ways, and a mute that acted on
a device it never touched.

Before you open it:

```bash
make check        # everything that needs no phone
```

CI runs the same commands, string for string — `scripts/check_workflow.py` fails the build if the
Makefile and the workflow ever drift — so a green `make check` here is a green CI there.

## Device reports are a contribution

This panel has run on exactly one phone. If you install it on another and it behaves differently
— the screen does not come back, a vendor list eats the process, a permission is refused — that
report is **as valuable as a patch**, and the bug form asks for the four things every diagnosis
here has started from.

[docs/PHONE-SETUP.md](docs/PHONE-SETUP.md) is the device-neutral half and is where a new device's
findings belong; [docs/INSTALL-PHONE.md](docs/INSTALL-PHONE.md) is one vendor's recipe and is
allowed to stay that way.

## A note on the `CLAUDE.md` files

They are instructions for AI agents working on this repository, in a register that will read as
strange to a human. They are not documentation and you never need to read them: anything in them
a contributor needs belongs in the documents above, and if you find something there that is not
here, that is a bug worth reporting.
