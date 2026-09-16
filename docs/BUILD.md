# Build

The entire Android toolchain lives in a Docker image. Nothing Android-related is installed on
the Windows host — that is a project requirement ([ADR 0003](adr/0003-containerized-toolchain.md)),
and `java -version` failing on the host is one of the acceptance checks.

## One-time setup

```powershell
wsl --install                      # reboot afterwards
winget install Docker.DockerDesktop
```

Then build the image:

```bash
docker compose -f docker/compose.yml build
```

The image carries JDK 21, the Android SDK command-line tools and platform 36. Gradle caches go
to a **named volume**, not a bind mount — bind-mounting `/mnt/d` through Docker Desktop is slow
enough to notice on every build.

## Building

```bash
docker compose -f docker/compose.yml run --rm build ./gradlew assembleDebug
# or
make apk
```

The APK lands in `out/`. The server picks it up from there and offers it at
`http://<pc-ip>:8777/app`, which is how it reaches the phone — see
[INSTALL-PHONE.md](INSTALL-PHONE.md).

## Where the web assets come from

`android/app/build.gradle.kts` points `assets.srcDirs` at `../../web`. The files shipped inside
the APK are the files in the repo — there is no copy step and no sync step. Editing
`web/index.html` and rebuilding is the whole loop.

## Signing

Create a release keystore once, at the repository root, and keep it out of git:

```bash
keytool -genkeypair -v -keystore desk-panel.keystore \
  -alias desk-panel -keyalg RSA -keysize 2048 -validity 10000
```

Put the path and the passwords in `keystore.properties`, also at the repository root:

```properties
storeFile=../desk-panel.keystore
storePassword=…
keyAlias=desk-panel
keyPassword=…
```

`storeFile` is resolved against the Gradle root, which is `android/` — so the keystore sitting
beside `keystore.properties` at the repository root is `../desk-panel.keystore`. A path that
resolves from the `android/app/` module is accepted too; the build tries the Gradle root first
and falls back to the module.

`.gitignore` already covers `*.keystore`, `*.jks` and `keystore.properties`. Verify rather than
assume — a password in the history is not something a later commit can remove, and this repo
goes public eventually:

```bash
git check-ignore -q keystore.properties
git check-ignore -q desk-panel.keystore
! git ls-files | grep -qiE '\.(keystore|jks)$|^keystore\.properties$'
```

**Back the keystore up somewhere outside the repository.** Losing it means never being able to
update this install again — only an uninstall, which throws away the device state.

### Building a release

```bash
docker compose -f docker/compose.yml run --rm build ./gradlew assembleRelease
```

The APK lands at `out/desk-panel-release.apk` (debug keeps its own name, `out/app-debug.apk`,
because the server and the E2E suite look for it there).

Confirm it really carries the release key — a build that silently fell back to debug signing
still produces an APK at the right path:

```bash
docker compose -f docker/compose.yml run --rm build \
  sh -lc '$ANDROID_HOME/build-tools/36.0.0/apksigner verify --print-certs out/desk-panel-release.apk'
```

The certificate DN is the one entered into `keytool`. `C=US, O=Android, CN=Android Debug` means
the fallback below kicked in.

### When `keystore.properties` is absent

It is gitignored, so it is missing on every fresh clone and in CI. There the release build
**falls back to the debug key** rather than failing, so a clone still builds and
`assembleRelease` still exits 0. The resulting APK is not installable over one signed with the
release key — only the machine holding the keystore can produce that.

**Use the release keystore from the start, including for local builds.** Alternating between
the debug key and a release key makes Android refuse to install over the existing app, and the
only way out is uninstalling — which throws away device state and the MIUI permissions you
spent time granting.

## Publishing (optional)

The owner has a Play Console account. Neither route below is required for personal use.

- **Internal app sharing** — upload, get a link, install from the phone. No store listing, no
  review, no automatic updates.
- **Internal testing track** — goes through the normal release flow but delivers automatic
  updates to enrolled testers. Handy for a device that lives on the desk.

Do not publish to the public store: the app points at a LAN IP and would neither pass review
nor make sense to anyone else.
