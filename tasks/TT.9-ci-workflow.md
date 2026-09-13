# TT.9 — CI workflow

Size: M · Prereqs: TT.1, TT.2, T2.1 · Files: `.github/workflows/ci.yml`

Requires: a pushed branch and the gh CLI authenticated

## Goal

Every push runs everything that does not need a phone.

## Steps

1. `.github/workflows/ci.yml` with three independent jobs, on push and pull request.
2. **server** — `actions/checkout`, `actions/setup-python` (3.13), then
   `python -m unittest discover -s server/tests -t .`. No pip install step: the server has no
   dependencies, and if this job ever needs one, that is a design regression worth catching.
3. **web** — `actions/checkout`, `actions/setup-node` (24 or newer), then
   `node --test "web/test/**/*.test.js"`. No `npm ci`: there is no `package.json`.
4. **android** — `actions/checkout`, `actions/setup-java` (21), `gradle/actions/setup-gradle`,
   then `./gradlew test` and `./gradlew assembleDebug`. Upload the APK with
   `actions/upload-artifact`.
5. Do **not** run `connectedAndroidTest` — it needs the physical device.
6. Never let CI hit the network for tests. `RUN_CONTRACT_TESTS` stays unset, so the contract
   tests skip.

## Acceptance

```bash
python -c "import sys,pathlib; sys.exit(0 if pathlib.Path('.github/workflows/ci.yml').is_file() else 1)"
python scripts/check_workflow.py
gh workflow run ci.yml --ref "$(git branch --show-current)"
gh run watch "$(gh run list --workflow=ci.yml --limit 1 --json databaseId -q '.[0].databaseId')" --exit-status
```

`check_workflow.py` parses the workflow and asserts the three jobs exist and run the same
commands the Makefile does — that is the part that keeps CI and `make check` from drifting,
which they already have. `gh run watch --exit-status` turns "confirm in the Actions tab" into
an exit code.

Note that `gh workflow run` needs the branch pushed, and `git push` is deliberately outside
the agent allowlist (`.claude/README.md`). A human runs this one, or authorises the push.

## Manual check

Break one test deliberately and confirm the right job — and only that job — goes red.

## Notes

- `setup-python`, `setup-node`, `setup-java` and `gradle/actions/setup-gradle` are first-party.
- `android-actions/setup-android` is **third-party and not GitHub-certified**. The Android job
  above avoids it by using `setup-java` plus the Gradle wrapper, which downloads what it needs.
  If it ever becomes unavoidable, note the dependency in the workflow.
- The CI Android job does not use the project's Docker image. That is fine — the image exists to
  keep the **developer's Windows host** clean, and a CI runner is disposable. The wrapper
  guarantees the same Gradle version either way.
