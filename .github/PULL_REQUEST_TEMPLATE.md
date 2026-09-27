<!-- Shaped like the pull requests this project already writes. Delete any
     heading that genuinely does not apply -- an empty one is worse than none. -->

## What changed, and why

<!-- The why is the part a reviewer cannot reconstruct from the diff. -->

## Which task file this closes

<!-- e.g. `tasks/T7.6-contribution-guide.md`, or "none - a fix found while
     doing something else". Work here is tracked in tasks/, indexed by
     tasks/STATUS.md. -->

## The acceptance command, and its exit code

```
$ 
```

<!-- Every task file's acceptance is a command with an exit code. Paste the
     one you ran. If this PR closes no task, `make check` is the baseline. -->

## Verified on the device, versus reasoned about

<!-- This project runs on one phone and one desk. Say which of these this is:

     - run on the phone / the PC, and what was observed
     - run in the browser harness or a suite, and which
     - reasoned about and not run anywhere

     All three are acceptable. Mixing them up silently is not - a green suite
     has shipped a dead button here before. -->

## What was deliberately left out

<!-- Every wave in this repository has had one. Scope you chose not to take,
     a follow-up worth filing, a limit you hit. -->

## Checks

- [ ] `make check` passes
- [ ] A decision that changes an invariant or contradicts an ADR has a new ADR beside it
- [ ] No new dependency, or an argument for one (see `docs/REQUIREMENTS.md`)
