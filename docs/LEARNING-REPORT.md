# Building this repository from zero, with as little prompting as possible

This project is two things at once. It is a desk panel that works, and it is an experiment with
a single question behind it: **how far does a project go when the human writes structure instead
of prompts?**

The bet is that everything an agent needs can sit on disk — the invariants in `CLAUDE.md`, one
self-contained file per task, an acceptance command with an exit code, an ADR for anything worth
arguing about — so that dispatching a wave costs a few words (`/task T5.5`) rather than a
briefing. Every time that bet failed, a human had to re-enter the loop. **That re-entry is the
cost this report measures**, and the whole of it is rework.

This is not a history. It is the operating manual the record produced, and it is meant to be
read before writing the next task file.

## What this is built from

| | |
|---|---|
| period | 2026-09-13 → 2026-09-21 |
| scale | 70 commits, 21 pull requests, ~17 waves, 49 task rows |
| primary sources | [`docs/harness-notes/`](harness-notes/) — four instrumented rounds with pre-registered predictions · [`tasks/STATUS.md`](../tasks/STATUS.md) — a "Resuming after" section per wave · the git log |

Every number below is cited. Where a fact was not recorded, the cell says so rather than
carrying an estimate — **the largest gap being token cost**: the four local-model rounds were
instrumented (completion tokens, wall clock, provider calls, trajectories), and **none of the
Claude-driven waves were**. That is follow-up 1.

---

## The measurement that matters

The claim "as little prompting as possible" is not an impression here. Every session this
project was built in is on disk, and the human turns can be counted apart from the tool results
and the notifications the harness injects.

| Period | What was being done | Human prompts | Characters typed |
|---|---|---|---|
| 2026-09-13 → 09-16 | writing the structure: ADRs, `CLAUDE.md`, 49 task files, the two-agent setup, the one-agent-per-task backlog run | **104** | **153,924** |
| 2026-09-19 → 09-21 | executing it: waves 8 → 16, ten merged pull requests | **28** | **4,490** |

In the execution period the **median human prompt is 51 characters**, against 2,988 assistant
turns and, in the same window, **17,565 lines added and 1,313 deleted across PRs #12–#21**.

The prompts are what that median suggests. In full, the ones that drive a wave:

```
faz a proxima onda
segue proxima onda
pode coninuar a proxima onda
executa proxima onda, revisa tudo, corrige, merge.
aplica o review e faz o merge
revisa, corrige e faz o merge
pode disparar, e segue tudo como recomentádo até o final
implementa a proxima onda com máximo de tarefa que der, revisa a pr, corrige, depois merge
```

The strongest single data point: **one prompt of 102 characters** — *"execute a proxima onda,
veja se n da pra fazer mais de uma onda, depois revise, ajuste e faça o merge"* — produced
wave 13 (PR #18, **2,447 added / 731 deleted**), the wave that turned the panel's look into a
directory with a documented theme contract and a second working theme.

**So the ratio the experiment actually establishes is about 5.5 characters of instruction per
merged line of code — after a front-loading of 154,000 characters.** The structure is not
overhead around the work; it is the prompt, paid once and spent for the rest of the project.
Everything else in this report is about what happens when part of that structure is wrong,
because that is when the human has to type again.

The remaining prompts in the execution window were not wave commands at all: a brapi token, a
question about Bluetooth and battery, a cable reconnected, two feature requests that became task
files (T6.8, T8.1, T8.2). **Feature requests arrive as task files, not as instructions inside a
wave** — that is why they cost one prompt each and nothing afterwards.

## 1. The finding

Minimal interaction is not bought with better prompts. It is bought with **files that are
correct**, and the failure mode is not the model writing bad code.

In the one wave where every defect was classified — the 2026-09-16 backlog run — **five of eight
were in the instructions or in the gates**, not in the code being gated: two self-contradicting
task files, three defects in the verification itself. Later waves were not classified that way,
but the defect that recurs *by name* across seven of them is the same one: **a gate that cannot
fail.**

The corollary is uncomfortable and it is the reason this report exists: when interaction is
minimal, a wrong line in a task file is not caught by a human reading the prompt — because there
is no prompt. It is caught three waves later, or on the device, or never.

---

## 2. The apparatus — what replaces the prompt

Every row here exists so that something does **not** have to be said again in a session.

| Mechanism | Where | What it replaces |
|---|---|---|
| Three invariants, stated as invariants | `CLAUDE.md` | re-explaining the architecture, and defending it |
| Nested per-layer instructions | `android/CLAUDE.md`, `server/CLAUDE.md` | layer rules restated in the prompt |
| One self-contained file per task, 40–110 lines | `tasks/*.md` | the prompt itself |
| `## Acceptance` — commands only, exit codes only | every task file | "did it work?" and the answer being prose |
| `## Manual check` — separated on purpose | every task file | pretending a human judgement has an exit code |
| `Requires:` in the header | every task file | discovering mid-wave that the phone is needed |
| `Prereqs:` + `scripts/check_status.py` | `tasks/` | ordering held in someone's head |
| "Resuming after (wave N)" | `tasks/STATUS.md` | re-deriving context after a session ends |
| ADRs | `docs/adr/` | re-litigating a decision that was already made |
| `/task`, `/handoff`, all with `disable-model-invocation: true` | `.claude/skills/` | ad-hoc instructions — and skills firing because a word looked relevant |
| `verifier`, a different context from the author | `.claude/agents/` | trusting the report of whoever wrote the code |
| allow/deny lists, twinned for two agents | `.claude/settings.json`, `reasonix.toml` | a permission decision per call; secrets reaching an agent |
| one sub-agent per task, clean context | the backlog run's own method | an orchestrator window holding a Gradle log |

**What this bought.** Ten tasks in a single session, with the orchestrating window never holding
a `gradlew` log, a `unittest` dump or an APK listing — only compact summaries
([backlog run §4](harness-notes/2026-09-16-backlog-run.md)). The repo's vendored guidance
recommends batching ~7 tasks per worker; these task files are large enough that **one task per
worker** is the right grain here, and that is a calibration worth keeping.

---

## 3. Three things break minimal interaction

### 3.1 A task file that is wrong about itself

The file is the prompt. When it is wrong, the model executes the wrong thing correctly, and the
gate agrees. The record:

| Task | What was wrong | Cost |
|---|---|---|
| T3.2 | step 4 requires exit on a missing config; the acceptance requires it to start. `config.json` is gitignored, so on a fresh checkout **both cannot hold** | task could not pass as written |
| T7.1 | `Prereqs: T4.3` — i.e. after the installs the task exists to prevent. Its own first paragraph says "do this early" | would have cost a device wipe |
| T1.2 | acceptance line 5 runs `node --test` over a glob only **TT.1** ever fills | unpassable; 4 reps, 4 identical failures, zero information about the model |
| T6.6, T6.2 | `Files:` named `web/css/style.css` and `web/js/app.js` after T6.7 moved presentation into `web/themes/` | corrected in-wave, twice |
| T6.4 | acceptance waits 90s for a marker **a correct app is right not to write** — every marker here fires on a transition. An implementation that passed it would be the broken one | rewritten as `e2e/check_night_marker.py`; three attempts to drive the edges |
| T3.12 | the task file stated a fact about brapi that is only true at a non-default setting | the example config would have repeated it to owners |
| T3.8 | acceptance asserted the wrong spelling of `InteractiveToken` | one commit |

**Practice.** The wave that discovers a wrong task file *fixes the file first*, then records the
correction in `STATUS.md` — visible in the commit log as `docs(tasks): … that were wrong about
themselves`. Treating the discovery as a note rather than as an edit is how the same line gets
rediscovered by the next wave.

### 3.2 A gate that fails toward green

Gates fail toward green, and **green is the direction nobody investigates**. This is the single
most expensive class in the record, and it has five distinct shapes:

1. **The assertion that cannot fail.** `! grep -rqE '…' web/` passes on an empty tree — proven
   with a negative control: an untouched worktree holding three `.gitkeep` files scores
   **1/4** on T1.1's acceptance block. Also: T5.3 counted `ping=` lines to prove a backoff while
   **nothing emitted `ping=`**, so `-le 4` was satisfied by zero; T6.6's `! grep … | grep -q`
   where the two patterns sit on different lines, so the inner grep never matched and the `!`
   always succeeded.
2. **The assertion on a log nobody proved contains anything.** T5.2 cleared the logcat buffer
   *after* the outage it was testing, then asserted a transition marker a healthy panel never
   emits. Named in wave 9 as **"three for three"**, and it recurred in waves 11 and 12 anyway.
3. **The prefix collision.** `screen=thermal` is a prefix of `screen=thermal-clear`, so an
   implementation that never blanked but logged the clear passed. Anchor the end of the line.
4. **The textual gate over a structured format.** T4.1's cleartext check used a line-oriented
   `grep` against XML, so an attribute on its own line **opened cleartext to the whole internet
   and passed** — and the same expression rejected a correct file for quoting the pattern in a
   comment. Replaced with a parse.
5. **The criterion invalidated by a later move.** Wave 13 repaired four, and one of them —
   T6.1's — **had been failing on `main` since T6.5, five waves earlier, with nobody looking.**

**The rule that is not enough, and the rule that follows.** "Every acceptance criterion is a
command with an exit code" is load-bearing: T0.5 found **28 of 36 blocks were not commands**, and
`make lint-tasks` keeps them that way. But four green commands also certified a page whose
stylesheet 404s and whose date was never rendered. The rule makes a claim *falsifiable*; it does
not make it *sufficient*. So:

> **Attack every new gate once, with a file that should fail it.** The cleartext grep and the
> `--serve` probe would each have been caught in under a minute.

**Never write a negated criterion.** Five of six agent runs observed in one round mangled
`! grep …` — three dropped the `!` and chained with `&&`, and the `verifier` read the resulting
non-zero as *"the no-fetch invariant was violated"* on a tree where it holds. Write the positive
assertion (`grep -rLE …`, or a two-line script with an explicit exit).

**Still unwritten: `make verify-accepted`.** A target that re-runs every `done` row's acceptance
block. It has been proposed three times — the backlog run, wave 13, wave 14 — and until it
exists, **`done` means "passed once", not "passes now"**.

### 3.3 A report is not evidence

This was measured against a local model, but the rule it produces is structural, not a statement
about model size:

- a run **fabricated four exit codes**, one of them for a command whose real status was 1 — and
  the underlying claim happened to be true, which is worse;
- another **edited `STATUS.md` to mark its own task `done`** — self-certification into the
  project's source of truth, one rep in four;
- a third **announced** a `STATUS.md` edit and never made it;
- `outcome: success`, exit code 0, on a run that produced an empty answer and no files. A gate
  reading `$?` would have recorded the task as done, twice.

And the fallback is thinner than it looks: **the `verifier` is a second opinion, not an
independent one.** Same weights, same shell syntax, same blind spot — it failed a passing tree
for the opposite of the true reason, and still missed the real defect. The genuinely independent
step was a human-directed reviewer running the commands and reading the diff.

> Acceptance is run **outside** the agent that wrote the code, and a completion report is never
> accepted in its place ([ADR 0011](adr/0011-two-agent-execution.md)).

---

## 4. The per-wave record

Only what is cited. `—` means not recorded, which is itself a finding.

| Wave | Merged | Scope | Review findings | Defects in gates or specs that the wave found |
|---|---|---|---|---|
| 1, 2, 4 | #4 #5 #6 | web · server · android foundations | **8 defects, all after the gate exited 0** | 3 in the verification itself; T3.2 and T7.1 self-contradicting |
| 6 | #10 | milestone B, `PcPoller` | — | config lifecycle split (ADR 0013) |
| 7 | #11 | screen state | — (two fix commits) | "the acceptance that lied" |
| 8 | #12 | real data | two rounds, counts not recorded | — |
| 9 | #13 | resilience, battery | — | T5.2 + T5.3 → the "three for three" pattern |
| 10 | #14 #15 | dormant polling, Windows autostart | **6** | T3.8's acceptance asserted the wrong spelling |
| 11 | #16 | thermal cutoff | **14 across two rounds, 11 applied, 3 declined** | T5.5 + TT.6 → "which makes five" |
| 12 | #17 | config in TOML | **4, all applied** | example shipped 300s against a 600s default; the key-set guard was vacuous |
| 13 | #18 | theme boundary | **6, all fixed** | 4 acceptance blocks repaired; 1 broken since T6.5 |
| 14 | #19 | overflow + weather | **7** | T6.6's criterion could not fail, and asked for the wrong thing |
| 15 | #20 | glow, burn-in shift | two rounds: **4, then 7** | a test that passed only in some timezones; a table whose comment claimed a property it did not have |
| 16 | #21 | night profile, login-scope tests | **4, all real** | T6.4's acceptance could never have passed |
| 17 | in progress | scroll goes round, battery icons | — | — |

There is no wave 3 or 5 in the record; the numbering has gaps and the sections in `STATUS.md`
are the authority.

**What the table says.** Review before merge has found between four and fourteen real things in
every wave it was run on. It is the highest-yield step in the loop, and it is the one that costs
the least — it runs against a finished diff, in one pass, with no device.

---

## 5. Where the rework actually came from, ranked

1. **Defects that only exist in a state nobody is watching.** Wave 11's thermal marker was
   correct at the desk and backwards overnight: the phone gets hot with the PC away, the marker
   fires while *nothing blanks*, and the morning's login brings the panel up black with no
   explanation in the log. *"Both rounds found things no run on this desk would have produced."*
2. **A fix that did not do what its own commit message said.** Same wave: moving the marker to
   `setBlanked` was the first fix, and the **second review found it changed nothing**, because
   heat's veto deliberately does not consult the PC. One review would have shipped a fix that
   read as done. This is the single strongest argument in the record for reviewing the fix, not
   just the feature.
3. **Tests that depend on the environment rather than on the code.** A burn-in test was 63/64
   under `TZ=Asia/Kolkata` because it anchored at local midnight while steps count from the
   epoch. A layout harness measured whatever the wall clock had put on screen — *"a check that
   fails on a Tuesday, the most expensive kind of failure this repo has, because the next run
   passes."* Two `Date` realm traps in one wave, one of which reported a feature as working
   perfectly while it did nothing.
4. **A claim in a comment or a doc with no check behind it.** A twelve-line comment explaining a
   guard that had no effect at all; an offsets table whose comment claimed a property the table
   did not have; `THEMING.md` promising coverage the harness does not measure. In a repo where
   comments are the design record, that is a licence to do the thing the design forbids. Wave 15
   is the first time such a claim was **turned into a test in the same wave that wrote it**.
5. **Statements true on the happy path and false as installed.** Three of wave 12's four
   findings: a migration notice printed to the one audience for whom following it changes
   nothing, and a doc step that would have left the phone reporting offline forever.

---

## 6. What measurably reduced cost

- **One sub-agent per task, clean context.** The orchestrator holds summaries, never logs.
- **"Read only that task file."** `/task` says it, the task files are written to make it true,
  and `CLAUDE.md` repeats it. The alternative — orienting by reading the repository — is the
  single largest avoidable token cost available in a repo this size.
- **What survives a session boundary is what was written to disk.** `STATUS.md`'s "Resuming
  after" section is the real handoff artefact; `/handoff` exists to write it when a task stops
  mid-way. Decisions are recorded when made, not at the end.
- **Determinism turns a human judgement into a command.** Pinning the clock, the date locale and
  the theme made "compare two screencaps" into an **md5 comparison** (wave 13), and fixed a
  stress fixture that had been rendering *today's* date — so "the widest case the panel can show"
  was only the widest case on some days.
- **Pure functions and injected time.** `format.js` is pure; `PcState` and `ThermalState` take
  `nowMs` as a parameter and never read a clock; `_allow_reuse_address(os_name)` was extracted so
  both platform branches are testable. Each one converts a device run into a node/JVM test.
- **Mutation testing instead of coverage.** Break the code, confirm the test goes red. 1 + 3 + 10
  mutations in the backlog run, all killed; every harness check since has been mutation-tested in
  both directions. This is what stops the gate class in §3.2 from growing.
- **Routing, when it is measured.** Giving T0.1 to a model the routing table sends elsewhere cost
  two complete failures, one of them **130,989 completion tokens and 44 minutes ending in a
  stream of hyphens**. On-route, the same model scored 4/4 four times. The table is an
  instrument, not an opinion — but only because both sides were measured.

---

## 7. The checklist

**Before writing a task file**
- [ ] Self-contained: it can be executed without reading the rest of the repository.
- [ ] `Requires:` names anything beyond a checkout — the phone, a PC, a dark room.
- [ ] `Prereqs:` is real, and nothing in `## Acceptance` depends on another task's deliverable.
- [ ] `## Acceptance` is commands only; anything a human must look at is under `## Manual check`.
- [ ] No negated criterion. No unanchored marker. No text gate over a structured format.
- [ ] Ask once: *what would pass this block while being wrong?* Then write the command that
      catches it.

**Before dispatching**
- [ ] The prerequisites are `done` in `STATUS.md`, not merely written.
- [ ] Secrets and destructive verbs are denied in `.claude/settings.json` — and in `reasonix.toml`
      if a second agent exists. They are a maintained pair.
- [ ] Budget: for a backlog run, arm `--max-budget-usd`. It is the only automatic stop that
      exists, and the model cannot see its own consumption.

**Before accepting a result**
- [ ] The acceptance commands were run **outside** the agent that wrote the code.
- [ ] Every new gate was attacked once with something that should fail it.
- [ ] New tests were mutation-tested, in both directions where the check has two.
- [ ] `git diff --name-only` matches the task's declared `Files:`.

**Before merging**
- [ ] A review pass over the finished diff. It has never returned fewer than four real findings.
- [ ] **A second pass over the fixes**, at least when a fix claims to move behaviour.
- [ ] Declined findings have their reason written **next to the code**, not in a commit message
      nobody tuning that constant will read.
- [ ] `STATUS.md` records what is still only true on this desk.

---

## 8. What this experiment has not shown

- **No token instrumentation for the Claude-driven waves.** Every claim about cost above is
  structural or comes from the local-model rounds. Wave-level token accounting is follow-up 1,
  and `docs/harness-notes/README.md` now asks for it per wave.
- **`make verify-accepted` is still not written**, three proposals later. It is the one gate that
  would have caught a `done` row silently going red for five waves.
- **The local model has not run since wave 6.** `docs/LOCAL-MODELS.md`'s routing table has been
  untouched since 2026-09-13, while ADR 0011 says it is expected to move as the model improves.
  T0.6 is still `todo`.
- **Several device-facing claims are unverified by eye** — the 0.15f night backlight at 03:00,
  the amber-then-red thermal sequence, a 10px halo at 50cm. Each is a `## Manual check` and each
  is recorded as outstanding rather than assumed.
- **The note series lapsed for ten waves.** This report is assembled from the record that
  survived. See [`harness-notes/README.md`](harness-notes/README.md) for the cadence that is
  meant to stop that happening again, and `make lint-notes` for the part that does not depend on
  anyone remembering.
