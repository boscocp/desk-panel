# 2026-09-16 — Running the backlog with one agent per task

A single session executing `tasks/` end to end: one sub-agent per task in a clean context, an
adversarial review of every result, one PR per wave. It stopped where the hardware stops.

The headline is not the code. **Eight defects were found, every one of them *after* the task's
own acceptance block had exited 0** — and the largest single category was defects in the
verification itself, not in the thing being verified.

---

## 1. What ran

| Wave | Scope | PR | `done` | `blocked` |
| --- | --- | --- | --- | --- |
| 1 | `web/` — T1.1, TT.1, T1.2 | [#4](https://github.com/boscocp/desk-panel/pull/4) | 3 | 0 |
| 2 | `server/` — T3.1, T3.2, T3.11, TT.2, TT.3 | [#5](https://github.com/boscocp/desk-panel/pull/5) | 1 | 4 |
| 4 | `android/` — T2.1, T4.1, TT.5 (+6 recorded) | [#6](https://github.com/boscocp/desk-panel/pull/6) | 3 | 6 |

Index at the end: **13 `done`, 11 `blocked`, 25 `todo`** of 49 rows.
Tests: **16 web**, **34 server**, **16 Android JVM**. Host still has no `java` and no SDK —
ADR 0003 holds.

Wave 3 (autostart) and waves 5–6 did not run: they queue behind the same two blockers as the
rest, below.

---

## 2. The eight defects

Every one passed the task's own gate. Ordered by what they teach, not by severity.

### Defects in the verifier — 3

**`probe.py --serve` reported success for code it never ran.** It launched `server.py`, then
polled the port until *something* answered — without checking that the answer came from the
child it had just started. With the port already busy, `server.py` failed to bind and exited,
and the probe exited 0 against the pre-existing listener. Reproduced with an impostor server:
exit 0, status 200, green.

This was not a curiosity. **T3.9 installs a systemd user unit on this machine listening on that
exact port.** After it, every `--serve` acceptance in T3.2, T3.4, T3.6 and T3.7 would have gone
green against the installed service instead of the working tree — a harness bug manufacturing
approval across four downstream tasks, invisible precisely because it was green.

**T4.1's cleartext gate approved what it exists to forbid.** The criterion was
`! grep -qE '<base-config[^>]*cleartextTrafficPermitted="true"'`. `grep` is line-oriented, so
`[^>]*` cannot cross a newline, and this passes:

```xml
<base-config
    cleartextTrafficPermitted="true">
```

Cleartext opened to every host on the internet, waved through by the gate guarding the
project's narrowest exemption. It fails the other way too — it matched a *comment* quoting the
forbidden pattern to explain it, rejecting a correct file for documenting itself. That false
negative is how it surfaced: the author hit it and rewrote the comment rather than question the
gate. A textual gate over a structured format is wrong by construction; replaced with a parse.

**`scripts/check_status.py` cannot see the cycle it was built to catch.** T3.1 declared
`Prereqs: none` while its acceptance ran `server/probe.py`, a T3.5 deliverable; T3.5 declared
`Prereqs: T3.1, T3.2`. The detector compares *declared* prereqs; this cycle ran through an
*acceptance command*. `probe.py` is a generic HTTP probe called by ten task files, so it moved
to its first caller.

### Contract mismatches between layers — 2

**`isNight` was dead code.** It took hour-of-day integers, and its tests only ever passed
integers. `server/config.example.json` ships `night_start: "22:00"`; the payload contract
carries `night: {start, end}` the same way. Fed those strings, every comparison coerced to
`NaN` and the function returned `false` for all 1440 minutes of the day. The night profile
would never have engaged, silently, and nothing would have errored.

**`formatPrice` zeroed cheap crypto.** `mock.js` deliberately carries a coin at `0.00081` to
prove the layout survives a long symbol and a tiny price, keeping six decimals so the jitter is
visible. `formatPrice` truncated to two, so that row read `$0.00` on every tick. Two tasks,
each internally consistent, disagreeing at the seam.

### Self-contradicting specs — 2

**T3.2 could not pass as written.** Step 4 requires the server to exit when `config.json` is
missing; the acceptance requires it to start. `config.json` is gitignored, so on a fresh
checkout it never exists and both cannot hold. Resolved in favour of step 4 — a server booting
with silently-empty config looks healthy and shows an empty panel, the failure mode this
project is least able to notice.

**T7.1's prerequisites pointed at exactly what it protects against.** `STATUS.md` argues at
length that T7.1 must come early, because Android refuses to install a differently-signed APK
over an existing one and the escape is an uninstall that discards every MIUI permission T2.4
spends a session granting. The header still read `Prereqs: T4.3` — Milestone B, far later. Run
literally, T7.1 could only happen after the installs it exists to prevent.

### Artefact hygiene — 1

**The APK shipped its own tests.** `assets.srcDirs` points at `web/`, which includes
`web/test/`, so `format.test.js` was packaged into the debug APK. Inert on the device, but real
bytes in a production artefact — and precisely what T7.3's pre-public review exists to catch,
except nobody would have opened the zip.

---

## 3. The regression nobody reported

T3.1 was accepted with both acceptance commands exiting 0. T3.2 then landed the hard fail on a
missing `config.json`, and T3.1's `probe.py --serve` began exiting 2 — **no T3.1 code changed,
nothing reported it, and the index kept saying `done`.**

It surfaced only because a verifier was pointed at the whole branch instead of at one task.

The cause is structural. `/task` runs an acceptance block **once**, at the moment the task
executes, and nothing ever runs it again. `make check` runs the *test suites*, not the
`## Acceptance` blocks. So a later task can invalidate an earlier task's criterion invisibly,
and the index will keep asserting otherwise.

**Worth building: `make verify-accepted`**, re-running the acceptance block of every row marked
`done` and failing on the first non-zero exit. Until it exists, **`done` means "passed once",
not "passes now"** — and that distinction is now written into `STATUS.md`.

---

## 4. What the setup got right

**One sub-agent per task, clean context.** The orchestrating window never held a `gradlew` log,
a `unittest` dump or an APK listing — only compact summaries. That is what made ~10 tasks
viable in one session. The repo's own `sub-agents.md` recommends batching ~7 tasks per worker,
calibrated for TLC's micro-tasks; these task files are 40–110 lines with their own `Requires:`
and acceptance block, so one task per worker is the right grain here.

**Author ≠ verifier, and it earned its keep every single time.** All eight defects were found
in review or by a fresh-context verifier. None was found by the gate that had just passed.

**Sub-agents refused to fake green — three times.** TT.2 stopped rather than invent
`providers_brapi.py` to have something to fixture. TT.3 covered `/ping` and 404 and declined to
assert `/quotes` behaviour that does not exist. T3.2 reported `blocked` rather than loosen its
own criterion. The `/task` contract's "do not silently reduce the scope of the task" held under
pressure — and the T3.2 case matters most, because loosening there would have hidden a spec
contradiction behind a green check.

**Mutation testing, not coverage.** Every suite was checked by breaking the code and confirming
the tests went red: 1 mutation on `load_config` (reviewer), 3 on the server (author), 10 on
`PcState` (author). All killed. The `PcState` set is the model — it covers *stuck* and
*flapping* separately, because a state machine that never transitions and one that transitions
on every probe both pass a happy-path suite.

**Testability forcing better structure, twice.** `_allow_reuse_address(os_name)` was extracted
from a class body because testing both platform branches otherwise required reloading the
module under a patched `os.name`, which crashes. `PcState` takes time as a parameter and never
reads a clock. Both are better designs that the test constraint produced, which is the argument
ADR 0006 makes for `format.js`.

---

## 5. What went wrong on my side

**I squashed six unpushed commits into the wrong PR.** Local `main` was six commits ahead of
`origin/main` — the T0.1 container work and four harness notes — and I branched wave 1 without
checking. The PR diffed against the stale remote, and the squash swallowed all of it into one
commit labelled "phase 1 web". No content was lost (trees identical, GitHub preserved all
twelve messages as bullets) but T0.1's work now lives inside a commit that claims to be
something else. Recommended against force-pushing a published `main` to fix cosmetics; added
`git fetch` + sync check before opening each wave, and waves 2 and 4 were clean.

**I contaminated a shared working tree with a mutation test.** Mutating `load_config` in place
left a stale `__pycache__/*.pyc` after I restored the source, and a concurrently running
sub-agent spent a diagnosis cycle on the phantom failure. This repo's own `validate.md` says to
run mutations in an isolated `git worktree` and never in place. I did not follow it.

---

## 6. Where it stopped, and why

Not scope — hardware and secrets. Eleven rows are `blocked`, each with its reason recorded
rather than left as `todo`, so the next session can tell "not started" from "cannot run here".

| Blocker | Blocks | Unblocked by |
| --- | --- | --- |
| `server/config.json` absent | T3.2, T3.3, T3.4, T3.5, T3.6, T3.7 (+ finishing TT.2, TT.3) | `cp server/config.example.json server/config.json` |
| Signing keystore absent | T7.1 | `keytool` in the container, passwords chosen by a human |
| Phone not on adb | T2.2, T2.3, T2.4, T4.2, T4.4, T5.1–T5.4, T6.3, TT.7, TT.8, T7.2 | attach the Redmi Note 10 |
| No Windows PC on the LAN | validation half of T3.8 | — |
| No Mac | T3.10 | — |
| Ollama model not loaded | T0.6 | `ollama run` the model from `docs/LOCAL-MODELS.md` |

The first two are one human command each and they are *correctly* out of reach: `.claude/settings.json`
denies `server/config.json` and `*.keystore` at read level, and routing around that denial with
`cp` would defeat a boundary the repository set on purpose.

---

## 7. What the official documentation says, and where this diverges

From `code.claude.com/docs`:

- **There is no token-count ceiling for a session.** [`MAX_THINKING_TOKENS`](https://code.claude.com/docs/en/costs.md)
  caps extended thinking only; `maxTurns` applies to sub-agents. The one documented hard stop is
  **`--max-budget-usd`**, which ends the session at a cost ceiling — in dollars, not in percent
  of plan.
- **The model cannot see its own consumption.** `/usage` and `/context` are client-side; their
  output never reaches the model. Any "stop at 10% of weekly" rule therefore depends on a human
  reporting the number, or on the flag being armed in advance. In this session the flag was
  **not** armed, so no automatic cut existed.
- Recommended reductions that this run used: sub-agents for context isolation, cheaper models
  for mechanical work, narrow prompts that avoid repository-wide scanning
  ([costs.md](https://code.claude.com/docs/en/costs.md#reduce-token-usage)).

Where this repository already agrees with [best-practices.md](https://code.claude.com/docs/en/best-practices.md)
without having copied it: *"give Claude a way to verify its work"* (every task carries commands
with exit codes) and *"add an adversarial review step"* (the `verifier` agent, author ≠
verifier). What is bespoke and **not** a documented pattern: the `/task` flow over numbered
files.

**Where this run diverges from the docs, on evidence.** The documented advice is to give the
model a way to verify its own work. This session's strongest result is that **the verification
needs verifying too**: three of eight defects were in gates, and gates fail toward green, which
is the direction nobody investigates. "Give it a way to verify" is necessary and not
sufficient — the gate deserves the same adversarial pass as the code, including a deliberate
attempt to *pass* it with something wrong.

---

## 8. If this is repeated

1. **Arm `--max-budget-usd` before starting.** It is the only automatic stop that exists.
2. **`git fetch` and confirm local `main` equals `origin/main` before branching a wave.**
3. **Seed the per-machine secrets first** — `config.json`, the keystore — or accept that a third
   of phase 3 cannot run.
4. **Attack every new gate once**, with a file that should fail it. The cleartext grep and the
   `--serve` probe would both have been caught in under a minute each.
5. **Mutate in a `git worktree`, never in place**, while other agents share the tree.
6. **Build `make verify-accepted`** before the backlog grows further. Past a certain size, "this
   was green once" stops being a useful claim.
