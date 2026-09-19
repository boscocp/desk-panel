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

## Local configuration: `.env`

Three things are machine-specific and have to be *inside* the APK: the PC's LAN address, which
the app is allowed to reach over cleartext; the release signing key; and which way up the panel
sits, which is a property of the stand rather than a preference. All live in a
gitignored `.env` at the repository root, read by Gradle at build time.
`.env.example` is committed beside it — copy it and fill it in.

```sh
PC_IP=192.168.15.3
PANEL_ORIENTATION=reverseLandscape
KEYSTORE_FILE=../desk-panel.keystore
KEYSTORE_PASSWORD=…
KEY_ALIAS=desk-panel
KEY_PASSWORD=…
```

`PANEL_ORIENTATION` takes `sensorLandscape` (the default), `landscape` or `reverseLandscape`;
anything else fails the build by name rather than surfacing later as an aapt2 complaint about a
manifest attribute. Leave it empty and the accelerometer decides, which is fine until the screen
sleeps for real — the wake relaunches the activity, the phone is lying nearly flat in its stand,
and the panel can come back upside down. Read the current one off the device with
`adb shell dumpsys window | grep -o "mRotation=ROTATION_[0-9]*"`; on the Redmi Note 10,
`reverseLandscape` is `ROTATION_270`.

**Never put an API token in `.env`.** The phone never talks to a data provider — it talks to
the PC, and the PC talks to the provider ([ADR 0004](adr/0004-server-is-login-signal-and-proxy.md)).
A value Gradle reads is a value compiled into the APK, and an APK is a zip file. Tokens, and
everything else the owner might want to change — tickers, city, intervals — belong in
`server/config.json`, which is read at run time and never leaves the PC. The split is
[ADR 0013](adr/0013-local-configuration-boundaries.md).

`PC_IP` must match the static DHCP reservation for the PC. **Changing it needs a rebuild and a
reinstall**: cleartext permission is a property of the APK, not of the server. Nothing else in
the project works that way, and that is exactly why the address is here and not in
`server/config.json`.

The committed `res/xml/network_security_config.xml` keeps the placeholder `192.168.1.100`.
Gradle substitutes `PC_IP` into a generated copy of `res/`, so the tracked file is never
rewritten and a real home network never reaches git. An absent or empty `PC_IP` leaves the
placeholder in place and the build still succeeds — a fresh clone builds, and produces an APK
that installs, runs, and cannot reach any PC.

Every build therefore says which address it baked in, on its first line:

```
desk-panel: cleartext pinned to 192.168.15.3 (from .env)
desk-panel: cleartext pinned to 192.168.1.100 (placeholder — no .env, the panel will not reach any PC)
```

An APK silently built against the placeholder is indistinguishable from a network fault. Read
that line before blaming the network.

A machine that predates this needs the migration once: move the four signing values out of
`keystore.properties` into `.env` under the names above and delete the old file. Both are
gitignored, so nothing in git changes.

## Signing

Create a release keystore once, at the repository root, and keep it out of git:

```bash
keytool -genkeypair -v -keystore desk-panel.keystore \
  -alias desk-panel -keyalg RSA -keysize 2048 -validity 10000
```

Put the path and the passwords in `.env`, as shown above.

`KEYSTORE_FILE` is resolved against the Gradle root, which is `android/` — so the keystore
sitting beside `.env` at the repository root is `../desk-panel.keystore`. A path that resolves
from the `android/app/` module is accepted too; the build tries the Gradle root first and falls
back to the module.

`.gitignore` already covers `*.keystore`, `*.jks`, `.env` and the old `keystore.properties`.
Verify rather than assume — a password in the history is not something a later commit can
remove, and this repo goes public eventually:

```bash
git check-ignore -q .env
git check-ignore -q desk-panel.keystore
! git ls-files | grep -qiE '\.(keystore|jks)$|^(keystore\.properties|\.env)$'
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

### When the signing values are absent

`.env` is gitignored, so it is missing on every fresh clone and in CI. There the release build
**falls back to the debug key** rather than failing, so a clone still builds and
`assembleRelease` still exits 0. The build says which key it used, next to the cleartext line:

```
desk-panel: release signing (from .env)
desk-panel: debug signing (no usable release key in .env — not installable over a release build)
```

The resulting APK is not installable over one signed with the release key — only the machine
holding the keystore can produce that.

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
