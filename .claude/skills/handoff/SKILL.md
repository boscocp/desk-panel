---
name: handoff
description: Record where the current task stands so another session can resume it
disable-model-invocation: true
---

The current task is stopping before it is finished. Record the state so the next session picks
it up without re-deriving anything.

1. Update the task's row in `tasks/STATUS.md` to `wip` or `blocked`.
2. In the Notes column, write, briefly:
   - what is already done and committed
   - what is left
   - what is blocking it, if anything
   - anything discovered along the way that is not obvious from the code
3. If the discovery answers one of the open questions at the bottom of `STATUS.md`, update that
   section too.
4. If the work changes a decision, update the relevant ADR. An ADR that contradicts the code is
   worse than no ADR.
5. Commit what exists, even if incomplete, on a branch. Say plainly in the commit message that
   it is partial.

Be concrete. "Still working on the poller" helps nobody; "PcPoller polls and logs correctly, but
the transition fires on every poll instead of once — likely the comparison in PcState.update()"
is worth the two minutes.
