# TT.9 — CI workflow

Size: M · Prereqs: TT.1, TT.2, T2.1 · Files: `.github/workflows/ci.yml`

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

Push a branch and confirm all three jobs pass in the Actions tab. Then break one test
deliberately and confirm the right job goes red.

## Notes

- `setup-python`, `setup-node`, `setup-java` and `gradle/actions/setup-gradle` are first-party.
- `android-actions/setup-android` is **third-party and not GitHub-certified**. The Android job
  above avoids it by using `setup-java` plus the Gradle wrapper, which downloads what it needs.
  If it ever becomes unavoidable, note the dependency in the workflow.
- The CI Android job does not use the project's Docker image. That is fine — the image exists to
  keep the **developer's Windows host** clean, and a CI runner is disposable. The wrapper
  guarantees the same Gradle version either way.
