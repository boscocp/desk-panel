# Running this repo with a local model

This repo is driven by two agents: Claude Code (Opus) over the Anthropic API, and
[Reasonix](https://github.com/esengine/DeepSeek-Reasonix) over a model running on the
desk machine. Both read the same `CLAUDE.md` files and the same `.claude/skills/`.
This document covers the parts that differ and which model to pick.

## Which local model

**`gemma4-128k-cc`** — Gemma 4 12B, Q4_K_M, 131072 tokens of context.

Measured on an RTX 5070 (12 GB): 8.1 GB resident, **100% GPU**, no CPU offload. It is
the largest model that fits with room for a full context window.

Pass@1 over 31 agentic coding tasks, two repetitions each, same harness and commit:

| model | pass@1 | median time to first solve | verdict |
|---|---:|---:|---|
| **`gemma4-128k-cc`** (11.9B) | **90% / 85%** | 53s / 64s | use this |
| `ornith-cc` (9B) | 60% / 70% | 24s / 30s | faster, 22pp worse |
| `lfm2.5-cc` (8.5B MoE) | 5% / 0% | — | unusable for agentic work |
| `qwen3coder-cc` (30.5B MoE) | not measured | — | 18 GB of weights; 51/49 CPU/GPU split, ~9× slower |

Two caveats on that table. The corpus was **Go**, not Java, Python or vanilla JS — the
ranking should hold, the absolute numbers need not. And `qwen3coder-cc` is untested
rather than bad: it is the obvious candidate the moment a 32 GB card exists.

`gemma4qat-cc` is the same model at int4 quantization-aware training, 7.7 GB, also 100%
GPU. Same context. Quality against `gemma4-128k-cc` has not been measured here — it is a
candidate, not a recommendation.

## What Reasonix picks up with no changes

Verified by running it, not by reading docs:

- **`CLAUDE.md`**, root and nested (`android/`, `server/`). Reasonix loads
  `REASONIX.md`, `AGENTS.md` and `CLAUDE.md` alike; nested files load as ancestor scope
  when work touches those directories.
- **`.claude/skills/`** — `handoff`, `task` and `tlc-spec-driven` all appear in its skill
  list alongside its own built-ins.

So the instructions and the skills need no duplication.

## What it does not read, and what replaces it

| Claude Code | Reasonix | why |
|---|---|---|
| `.claude/settings.json` | `reasonix.toml` | the permission and hook schemas differ, so Reasonix skips the file rather than misparse it |
| `.claude/agents/verifier.md` | `.reasonix/skills/verifier/SKILL.md` | different frontmatter: `Read/Grep/Glob/Bash` and `model:` versus `read_file/grep/glob/bash` and the session's model |

**Keep each pair in step**, and `make lint-permissions` is that rule with an exit code —
`scripts/check_permission_parity.py`. Adding a command to `.claude/settings.json` without
adding it to `reasonix.toml` means the local agent stops at an approval prompt the other one
sails through, which costs a whole turn of a 12B model.

The checker compares command *families*, not spellings: `Bash(make check)`,
`Bash(make check *)` and `Bash(make check:*)` are one rule. Asymmetries that are meant are
declared in `reasonix.toml` beside the rules they cover:

```toml
# parity: intentional — Bash(git commit:*), Bash(git push:*): git belongs to the
# reviewing agent (ADR 0011).
```

Every `Tool(spec)` named in such a comment block is exempt, and a declaration that no longer
describes a real difference fails the check too — a stale exemption hides the next drift.
There are four of them today: the shell inspection commands (Claude reads with its native
`Read`/`Grep`/`Glob` and needs no `Bash(cat:*)`), `WebFetch`, the two git write commands, and
the keystore glob below.

Three syntax traps, all confirmed against the Reasonix source:

- `Bash(cmd:*)` is canonical; Claude Code's `Bash(cmd *)` also parses, so that half ports
  verbatim.
- `Edit(path)` covers every file-mutating tool. **`Read(path)` does not map** — Reasonix's
  reader is `read_file`, and a `Read(...)` rule copied across is silently inert.
- `WebFetch(domain:...)` has no equivalent.

Secrets are therefore protected by `[sandbox] forbid_read` in `reasonix.toml` rather than
by a `Read(...)` deny. That is the better mechanism anyway: it blocks `cat` too. Verified
with a decoy token in `server/config.json` — `read_file` reported the file as
non-existent and `cat server/config.json` returned `Permission denied`.

**`forbid_read` matches literal paths only.** Measured 2026-09-23 in a scratch fixture: with
`forbid_read = ["*.keystore"]`, `cat a.keystore` printed the decoy; with the entry spelled out
as `a.keystore`, the same command returned `Permission denied`. Claude Code's
`Read(./*.keystore)` deny *is* a glob, so the two files cannot say this the same way — the
keystore is listed by name in `reasonix.toml`, the glob is declared intentional, and a second
keystore added to the repository needs a second line or it is readable by the local agent.

## The model and the provider are pinned in the repository

`reasonix.toml` carries `default_model` and a `[[providers]]` block, so a clone resolves the
same model this desk used:

```toml
default_model = "ollama-local/gemma4-128k-cc"

[[providers]]
name = "ollama-local"
kind = "openai"
base_url = "http://localhost:11434/v1"
default = "gemma4-128k-cc"
api_key_env = ""
context_window = 131072
```

They used to live in an untracked `~/.reasonix/config.toml`, which made "it worked here"
unreproducible and unreviewable (ADR 0011).

`context_window` is not decoration: at **0 the harness disables compaction entirely** and the
run dies of context exhaustion instead of compacting. It must match the `num_ctx` the model's
own Modelfile declares — Reasonix does not detect a server-side truncation, so a larger number
is silently wrong.

One end-to-end check that the pinned provider resolves, and the mode trap in it:

```bash
reasonix run --dir . --permission-mode manual --max-steps 5 "print the repository name and stop"
```

The modes are `manual | ask | auto | acceptEdits | dontAsk | plan | bypassPermissions`. There is
no `read-only`, and `plan` — the read-only one — refuses to run headless with
`--permission-mode plan requires an interactive session`. `manual` is the strictest mode `run`
accepts.

## The limit that decides how you use it

**The local model reports work it did not do.**

Asked to run two commands, it ran the first and then wrote: *"O segundo comando,
`touch NAO-DEVIA-EXISTIR.txt`, criou um arquivo vazio"*. The trajectory shows it never
issued the second tool call at all. When the same command really was dispatched and the
permission gate refused it, the model reported the refusal accurately — so this is not a
gate problem. It is the model narrating a plausible outcome instead of an observed one.

Everything else follows from this:

- **Never accept a completion report from the local model.** Run the task's acceptance
  command yourself, or hand the task id to the `verifier` subagent, which exists for
  exactly this reason.
- This is why `CLAUDE.md` says every acceptance criterion is a command with an exit code.
  With a local model that rule stops being good hygiene and becomes load-bearing.

## Which tasks to give it

Good fit — greenfield files, one self-contained task file as the spec, a test command
that settles it:

- `T1.1` clock in plain HTML/JS
- `T1.2` `mock.js` fixtures
- `TT.1` extract `format.js` + `node:test`

The `tasks/` design — self-contained files, "do not read the whole repository to get
oriented" — happens to be exactly what a 12B model needs. Writing new files also plays to
its strengths; the measured weakness is surgical edits to existing code, where it
repeatedly misses the anchor text.

Give to Opus instead:

- `T0.1` containerised toolchain, `T2.1` Gradle — Docker and Gradle specifics
- `T2.4` MIUI smoke test — the riskiest unknown in the project
- Anything under `docs/adr/`, and any change to an invariant
- The `tlc-spec-driven` skill: 227 lines plus 127 KB of references is more procedure than
  a 12B model follows reliably

## Commands

```bash
reasonix                                     # interactive, uses gemma4-128k-cc
reasonix run -p "implement T1.1"             # headless, prints the final answer
reasonix subagent run verifier "T1.1"        # independent check of the acceptance criteria
reasonix --model ollama-local/gemma4qat-cc   # the QAT variant, for comparison
ollama ps                                    # PROCESSOR must read 100% GPU
```

If `ollama ps` shows anything but `100% GPU`, something else took the VRAM before the
model loaded — close it and reload. The gap between full GPU and a partial offload is
roughly ninefold.
