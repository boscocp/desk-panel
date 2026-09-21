# Harness notes

One note per round. [ADR 0011](../adr/0011-two-agent-execution.md) states the rule and the
reason: *"Each run leaves a trajectory, and each round leaves a note in `docs/harness-notes/`
— where the model lost the thread, whether it claimed unperformed work, how much of the diff
needed correction. The point of the experiment is that record, not only the merged code."*

[`../LEARNING-REPORT.md`](../LEARNING-REPORT.md) is what these notes are for: the aggregate,
re-read before writing the next task file.

## The two kinds of round

| | **Local-model round** | **Wave** |
|---|---|---|
| file | `YYYY-MM-DD-<task-id>.md` | `YYYY-MM-DD-wave-<N>.md` |
| what ran | Reasonix + a model served by Ollama, reps under a declared protocol | Claude Code executing one wave to a merged PR |
| instrumented | yes — trajectories, `--metrics`, completion tokens, wall clock | **no, and that is the open gap.** Record what you have |
| examples | the four notes from 2026-09-14 and 2026-09-16 | `2026-09-21-wave-16.md` |

A local-model round keeps its pre-registered predictions and scores them; that protocol is
already demonstrated in the existing four notes and is not repeated here.

## What a wave note must contain

Three headings, and `make lint-notes` fails without them:

- `## What ran` — the tasks, the branch, the PR, the diff (`gh pr view <n> --json additions,deletions`).
- `## What the review found` — how many findings, how many applied, how many declined **and
  why**. If a fix was itself reviewed and did not do what its commit message claimed, that is
  the most valuable line in the note.
- `## What is not proven` — what was verified by command, what only by eye, what is still only
  true on this desk. A wave with nothing outstanding says so in one line.

Two more are expected wherever there is anything to say, and they are where the reusable
learning lives:

- `## Where the rework went` — every place a human had to re-enter the loop, and what would have
  prevented it. A wrong task file, a gate that could not fail, a fix that needed a second pass.
- `## Cost` — prompts typed, and tokens or wall clock **if they were measured**. Do not estimate
  them; an empty cell is a finding and a guess is noise.

Keep it short. These notes are read before a wave, not after a release.

## The gap, 2026-09-16 → 2026-09-21

**Waves 7 to 15 have no note.** The series ran for four rounds, stopped when the local-model
experiment paused, and the record migrated into `tasks/STATUS.md`'s per-wave "Resuming after"
sections — which are good and were never meant to carry it. Nothing enforced the rule, so
nothing kept it.

Those waves are reconstructed in `../LEARNING-REPORT.md` from `STATUS.md`, the git log and the
merged PRs. That is second-hand by construction: it recovers what was found and fixed, and it
cannot recover what a note is actually for — where the loop stalled and what it cost.

`make lint-notes` is the part that does not depend on anyone remembering. It requires a note for
every wave from **16** onward, which is the first wave for which one exists; earlier waves are
the recorded backlog and are not failed retroactively.
