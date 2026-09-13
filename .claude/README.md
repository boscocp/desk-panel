# Agent configuration

## settings.json

A deliberately **conservative** allowlist: tests, builds, and read-only git plus `add` and
`commit`.

Three things are **not** in it, on purpose:

- **`git push`** — publishing is a decision, not a step. Add it yourself if you want that.
- **`defaultMode: "auto"`** — full autonomous execution is a choice worth making explicitly
  rather than inheriting from a bootstrap commit.
- **Anything destructive** — no `rm`, no `reset --hard`, no `clean`.

Secrets are denied at read level, not just write: `server/config.json` holds the brapi token
and `keystore.properties` holds signing passwords. An agent has no reason to read either, and
this repo becomes public later.

Put machine-specific additions in `settings.local.json`, which is gitignored.

## Skills

- `/task T3.3` — loads that task file and executes it, then updates `tasks/STATUS.md`.
- `/handoff` — writes down where things stand when a task is stopping mid-way.

## Agents

- `verifier` — runs a task's acceptance criteria in a clean context and reports pass or fail,
  without the bias of having just written the code.

## Hooks

None are enabled. A `PostToolUse` hook running the tests of the edited layer is the obvious
candidate, and it is deliberately left off until the test suites actually exist — a badly
calibrated hook in an empty repo gets in the way more than it helps.
