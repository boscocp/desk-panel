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

Create a release keystore once and keep it out of git:

```bash
keytool -genkeypair -v -keystore desk-panel.keystore \
  -alias desk-panel -keyalg RSA -keysize 2048 -validity 10000
```

Put the path and passwords in `keystore.properties` (gitignored, and read by
`build.gradle.kts`). `.gitignore` already covers `*.keystore`, `*.jks` and
`keystore.properties`.

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
