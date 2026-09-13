# 0011 — Two agents: the local model executes, Claude reviews

Status: accepted · 2026-09-13

## Context

This repository is driven by two agents: Claude Code over the Anthropic API, and
[Reasonix](https://github.com/esengine/DeepSeek-Reasonix) over a model served locally by Ollama
on the desk machine. Both read the same `CLAUDE.md` files and the same `.claude/skills/`.

That arrangement arrived whole in PR #1 — `reasonix.toml`, `.reasonix/skills/verifier/`,
`docs/LOCAL-MODELS.md` — with no task file, no `STATUS.md` row and no ADR, in a repository whose
own rules make `tasks/` the unit of work and `docs/adr/` the place decisions live. This ADR is
that record, written after the fact, because the division of labour it implies now shapes how
tasks are written.

Two properties of the tools decide the shape, and neither is a preference:

- **The local model reports work it did not do.** Recorded in `docs/LOCAL-MODELS.md`: asked to
  run two commands, it ran the first and then described the second one's result in detail. The
  trajectory shows the tool call was never issued.
- **Reasonix performs no completion check.** Its own documentation is explicit that the
  completion validator was removed, and that goal completion is a declaration by the model with
  no host-side quality gate behind it. It also never commits, branches, or opens a pull
  request — it has no git tool; a model can only reach `bash git ...` through the permission
  gate.

Together these mean a completion report from the local side is an unverified claim, by design
on both sides.

## Decision

**The local model executes. Claude prepares and reviews. Git belongs to Claude.**

1. **Preparation.** Claude turns a task file into the prompt, with the payload contract and the
   relevant nested `CLAUDE.md` referenced explicitly — Reasonix loads nested instruction files
   lazily, on `@`-reference, so a layer's rules are not in context unless they are named.
2. **Execution.** Reasonix runs with `--permission-mode workspace-write`, an explicit
   `--max-steps` (the default is unbounded), and `--trajectory` recording the run.
3. **Verification.** The task's acceptance command is run **outside the harness**, by Claude or
   by the `verifier`. A completion report is never accepted in its place. This is why every
   acceptance criterion has to be a command with an exit code, and why `make lint-tasks`
   enforces it — with a local model, that rule is load-bearing rather than tidy.
4. **Publication.** Claude creates the branch, writes the conventional commit, opens the PR.
   `git commit` and `git push` are denied to the local agent in `reasonix.toml`.
5. **Review.** The PR is read by a human, with the diff — not the report — as the record of
   what happened.

**Routing.** Greenfield files with a self-contained task file and a settling test command go to
the local model; its measured weakness is surgical edits to existing code, where it misses the
anchor text. Architecture, invariants, ADRs and anything spanning layers stay with Claude. The
current split lives in `docs/LOCAL-MODELS.md` and is expected to move as the model improves.

## Consequences

- Every task handed to the local model must have an acceptance command that settles it without
  a human reading output. Tasks that fail that test are rewritten before dispatch, not after.
- The two permission files are a maintained pair — `.claude/settings.json` for Claude,
  `reasonix.toml` for Reasonix, which deliberately does not read the former. They drifted
  within one PR of being declared twins, so T0.6 adds a parity check rather than another
  sentence asking people to remember.
- The model and provider are pinned in `reasonix.toml` (T0.6). Leaving them in an untracked
  global config made "it worked on this machine" unreproducible and unreviewable.
- Each run leaves a trajectory, and each round leaves a note in `docs/harness-notes/`: where the
  model lost the thread, whether it claimed unperformed work, how much of the diff needed
  correction. The point of the experiment is that record, not only the merged code.
- `WebFetch` has no Reasonix equivalent, so tasks that need upstream API documentation — T3.3
  and T3.4 — are not local-model work regardless of their shape.

## Alternatives considered

**Let the local agent own its commits.** Rejected: with no completion check and a model that
narrates unperformed work, the commit would be the first place the fiction became permanent.
Keeping git on the reviewing side makes the diff the artefact under review.

**Have Claude execute and the local model review.** Backwards. Reviewing demands more
reliability than writing a greenfield file, not less — a reviewer that invents observations is
worse than no reviewer.

**Drop the local model.** It would cost nothing today and give up the point of the project as
an experiment. The measurements in `docs/LOCAL-MODELS.md` exist to make that call later with
evidence.
