# Context Limits

## File Size Limits

| File      | Max Tokens | ~Words | Warning At |
| --------- | ---------- | ------ | ---------- |
| spec.md   | 5,000      | 3,000  | 4,000      |
| design.md | 8,000      | 4,800  | 6,400      |
| tasks.md  | 10,000     | 6,000  | 8,000      |

These are limits on what this skill *writes*. A spec that needs 8k tokens is a spec covering two
features - split it, do not raise the cap.

## Loaded Context

Claude Code reports the real budget with `/context`; the window depends on the model in use, so
never quote a fixed total. What matters is the share this skill's artifacts occupy:

🟢 **Healthy** - artifacts under ~20% of the window: silent
🟡 **Moderate** - ~20-40%: note it once, drop what the current phase does not need
🔴 **Critical** - over ~40%: stop loading, summarise into `.specs/STATE.md`, and continue from
the summary

Never hold two feature specs, or two design docs, at once.

## Sub-Agents Are the Real Lever

A batch worker or the Verifier gets a fresh window. Pushing a phase into one keeps this
conversation lean far more effectively than trimming reads here - see
[sub-agents.md](sub-agents.md).

## Long Sessions

When the conversation grows long, Claude Code summarises it and continues; work does not have to
stop at a context boundary. What survives a summary is what was written to disk - `.specs/STATE.md`,
`tasks.md` checkboxes, commits. Record decisions when they are made, not at the end.
