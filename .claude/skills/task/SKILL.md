---
name: task
description: Load and execute a numbered task from tasks/, then update STATUS.md
disable-model-invocation: true
---

Execute the task identified by `$ARGUMENTS` (for example `T3.3`, `TT.6`).

1. Find the matching file in `tasks/` — the name starts with the id, as in
   `tasks/T3.3-quotes-proxy.md`.
2. Read **only** that file, plus `CLAUDE.md` and whichever nested `CLAUDE.md` covers the layer
   being touched. Each task is written to be self-contained; do not read the whole repository to
   get oriented.
3. Check its prerequisites against `tasks/STATUS.md`. If one is not `done`, stop and say so
   rather than working around it.
4. Implement it.
5. Run the acceptance command from the task file. It exits 0 or the task is not finished.
6. Update `tasks/STATUS.md`: mark the task `done` and note anything the next session needs.
7. Commit with a conventional-commit message, in English, **with no Claude attribution and no
   Co-Authored-By line**.

If you get blocked, mark it `blocked` in `STATUS.md` with the reason and stop. Do not silently
reduce the scope of the task.
