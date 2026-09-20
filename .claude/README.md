# Agent configuration

## settings.json

A deliberately **conservative** allowlist: tests, builds, and read-only git plus `add` and
`commit`.

Three things are **not** in it, on purpose:

- **`git push`** — publishing is a decision, not a step. Add it yourself if you want that.
- **`defaultMode: "auto"`** — full autonomous execution is a choice worth making explicitly
  rather than inheriting from a bootstrap commit.
- **Anything destructive** — no `rm`, no `reset --hard`, no `git clean`.

`make clean` is the one sanctioned exception in spirit and is still not allowlisted: it runs
`rm -rf out` and `./gradlew clean`, so it prompts. That is the intended friction — deleting
build output is cheap to redo and easy to confuse with deleting something else.

Secrets are denied at read level, not just write: the real config holds the brapi token
and `keystore.properties` holds signing passwords. An agent has no reason to read either, and
this repo becomes public later.

Put machine-specific additions in `settings.local.json`, which is gitignored.

## Skills

- `/task T3.3` — loads that task file and executes it, then updates `tasks/STATUS.md`.
- `/handoff` — writes down where things stand when a task is stopping mid-way.
- `/tlc-spec-driven` — a full specify → design → tasks → execute workflow for a feature that has
  no task file yet and does not fit one. Vendored from
  [tech-leads-club/agent-skills](https://github.com/tech-leads-club/agent-skills) (CC-BY-4.0) and
  adapted; `SKILL.md` ends with the list of local changes, so an upstream re-sync has something
  to re-apply. It writes to `.specs/`, which is additive — `tasks/` stays the default flow, and
  anything worth keeping afterwards ends up as an ADR or a task file.

All three set `disable-model-invocation: true`: they run when you type them, never because the
model decided a message looked relevant. `/tlc-spec-driven` in particular is heavy — several
phases, sub-agents, its own validation scripts — and would be wrong to trigger on a passing
mention of the word "design".

## Agents

- `verifier` — runs a task's acceptance criteria in a clean context and reports pass or fail,
  without the bias of having just written the code.

## Hooks

None are enabled. A `PostToolUse` hook running the tests of the edited layer is the obvious
candidate, and it is deliberately left off until the test suites actually exist — a badly
calibrated hook in an empty repo gets in the way more than it helps.
