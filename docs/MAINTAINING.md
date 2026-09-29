# Maintaining the repository

What GitHub does for this project, why it costs nothing, and the parts that are
written down here because they are decided outside every file in the tree.

This document covers the automation (CI, linting, dependency updates, code
scanning) and, at the end, the repository settings T7.7 applies, as commands
that can be re-run.

## Everything here is free *because the repository is public*

Two assumptions carry the whole setup, and neither is visible from inside a
workflow file:

- **GitHub-hosted Actions minutes are unlimited on public repositories** and
  metered on private ones. Every workflow in `.github/workflows/` runs on
  `ubuntu-latest`, on every push and every pull request.
- **CodeQL code scanning is free on public repositories** and requires GitHub
  Advanced Security — a paid product — on private ones. The same is true of
  `dependency-review-action`, which reads the code-scanning dependency graph.

**Making this repository private makes both of those false.** The minutes start
being billed, and the two security features stop working rather than becoming
expensive quietly. That is a decision about this file as much as about
visibility, so make it here first.

`concurrency:` is set on every workflow anyway, cancelling superseded runs on
the same ref, because three pushes to a branch should leave one run and not
three. Free minutes are not a reason to spend twenty of them per push.

## What runs, and where

| Workflow | Jobs | What it proves |
|---|---|---|
| `ci.yml` | `server`, `web`, `android` | the three test suites, run exactly as the `Makefile` runs them. `scripts/check_workflow.py` fails on any difference between the two files. |
| `lint.yml` | `lint`, `guards` | `ruff`, `node --check`, PSScriptAnalyzer, `shellcheck`; and the repo's own guard scripts, which nothing ran unless a human remembered. |

Locally, `make check` runs everything that does not need the phone, including
every guard `lint.yml` runs. That is deliberate: a contributor should be able to
fail before pushing, not after.

### Why the linters are the ones they are

- **`ruff`** is installed in the job and never in `server/`. The server is
  standard library only (`server/CLAUDE.md`); a linter that shipped with it
  would be the rule it exists to keep. Configured in `pyproject.toml`, which
  is linter configuration and *not* a package definition — nothing in this repo
  is installed with `pip`.
- **Not ESLint.** `web/` has no `package.json` and no build step, by design
  ([ADR 0006](adr/0006-no-framework-web-layer.md)). Adding a node toolchain to
  lint a no-toolchain directory is the tail wagging the dog. CI runs
  `node --check` on every file under `web/`, which is already more than that
  directory promises.
- **PSScriptAnalyzer** reads `server/install_task.ps1`, the one file here that
  nobody on the development machine can run. That makes it the file most worth
  having a machine read. Its *errors* fail the job; its style warnings are
  printed and do not, because a style opinion about a file no test can exercise
  is not worth blocking a stranger's pull request.

### Actions are pinned to commit SHAs

Every `uses:` names a 40-character SHA with the version in a trailing comment.
A tag is mutable, and a compromised popular action runs with whatever the token
allows. `scripts/check_ci_hygiene.py` fails on an unpinned one — including
`actions/*` and `github/*`, which GitHub's own hardening guide asks for and
which this repo pins too rather than maintaining an exemption list.

The cost of pinning is that a human never sees a version bump, so Dependabot
does it: `.github/dependabot.yml` covers `github-actions`, `gradle` and
`docker`, weekly, each grouped into one pull request. `pip` and `npm` are
deliberately absent and the checker fails if either is added, because a config
naming an ecosystem the repo does not have looks like coverage and is not.

To re-pin an action by hand:

```bash
gh api repos/actions/checkout/releases/latest --jq .tag_name
gh api repos/actions/checkout/git/ref/tags/<tag> --jq .object.sha
```

An annotated tag answers with `"type": "tag"` rather than `"commit"`; dereference
it with `gh api repos/<owner>/<repo>/git/tags/<sha> --jq .object.sha`.

## Not enabled yet: CodeQL and dependency review

Both are free on a public repository and both need GitHub Advanced Security on a
private one. **This repository is still private**, and
`gh api repos/<owner>/<repo>/code-scanning/default-setup` answers `403 Code
scanning is not enabled for this repository`.

They are therefore deliberately absent rather than added and broken. A workflow
that arrives red teaches everyone to scroll past it — which is exactly what the
bootstrap `ci.yml` did for twenty-two waves — and a check that cannot pass is
worse than a check that does not exist.

**Turn both on in the same session that makes the repository public** (T7.7):

1. Enable CodeQL default setup in *Settings → Code security → Code scanning*.
   It reads Python, JavaScript and Java, which is all three of this repo's
   languages, and it needs no workflow file. Confirm with:

   ```bash
   gh api repos/<owner>/<repo>/code-scanning/default-setup
   ```

   If default setup does not offer all three languages, add a workflow instead.
   Keep the file's top-level `permissions: contents: read` — `check_ci_hygiene.py`
   rule 1 requires one on every workflow — and add `security-events: write`
   **on the job**, where it is the narrower of the two. Pin
   `github/codeql-action/init` and `.../analyze` to SHAs like everything else;
   rule 2 grants `github/*` no exemption.

2. Add `dependency-review-action` in **its own workflow file**, `on:
   pull_request`, not as a job in `lint.yml`. The action only works in a pull
   request context, and `lint.yml` also runs `on: push`, so a job there would
   need an `if:` — which `check_ci_hygiene.py` rule 6 bans outright, for the
   reason wave 23 found. A separate file needs no condition to express. The new
   file needs `permissions: contents: read` and a `concurrency:` block like
   every other, or rules 1 and 3 fail it. It is nearly a no-op in a repo with
   almost no dependencies, which is the point: it is how the repo *notices* the
   day that changes.

3. Confirm in *Settings → Billing* that the Actions minutes show as unbilled,
   and delete this section.

## Deliberately absent

No stale-issue bot, no auto-labeller, no "thanks for your contribution" action.
This project expects a handful of contributors and device reports (T7.7).
Automation that answers a human with a robot costs more goodwill than it saves
time.

## Repository settings (T7.7)

Settings clicked in the web UI are lost the first time the repository is moved
or recreated, so every one of them is a command here. Run from the repository
root with an authenticated `gh` that has admin on it.

### Labels

One per area of the codebase, plus the three the contribution guide promises.
`--force` makes each line idempotent.

```bash
gh label create device-report --color 1d76db --description "It works, or does not, on a phone we have not seen" --force
gh label create needs-adr     --color d93f0b --description "Touches an invariant: an ADR comes before the PR" --force
gh label create good-first-issue --color 7057ff --description "Small, real, and taken from the backlog" --force
gh label create area:web      --color c5def5 --description "web/: the panel UI" --force
gh label create area:server   --color c5def5 --description "server/: the PC half" --force
gh label create area:android  --color c5def5 --description "android/: the phone half" --force
gh label create area:harness  --color c5def5 --description "scripts/, tasks/, CI" --force
```

### Discussions

For "will it run on my phone?", which is a question and not a bug. The issue
template chooser links there.

```bash
gh api -X PATCH repos/{owner}/{repo} -F has_discussions=true
```

### Branch protection on `main`

PRs only, CI green, no force-push, no deletion. **It applies only once the
repository is public**: on GitHub Free, a private repository answers this call
with 403, *"Upgrade to GitHub Pro or make this repository public"*, and that is
why it is the first command to run after the visibility flip. No review is
required, since the maintainer is one person, but a PR is.

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": false, "contexts": ["server", "web", "android", "guards", "lint", "secrets"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

`enforce_admins` is off on purpose. It is what would let the maintainer merge a
fix while CI itself is broken, which is a real case for a one-person repo.

### Review and ownership

`CODEOWNERS` names the maintainer, so every PR requests a review automatically.
The PR template asks what was verified on the device and what was only reasoned
about; a PR is merged after its review is applied, not before.

### What a PR needs before merge

- CI green: the six checks above.
- The PR template answered, especially "verified on the device, versus reasoned
  about". Either answer is acceptable; mixing them up silently is not.
- For anything touching an invariant, an ADR merged first or in the same PR.
- A PR that is good but cannot be verified without the hardware is labelled
  `device-report` and waits for one, rather than being merged on trust or closed.

