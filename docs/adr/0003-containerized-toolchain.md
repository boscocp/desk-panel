# 0003 — Containerised Android toolchain

Status: accepted · 2026-09-13 · context amended by [0010](0010-login-signal-is-session-scoped.md),
which made Linux and macOS hosts too; the `adb` question settled by T7.2

## Context

Building an APK normally means installing Android Studio, which drops several gigabytes across
the Windows user profile: the SDK in `%LOCALAPPDATA%`, Gradle caches in `%USERPROFILE%\.gradle`,
a bundled JDK, plus registry entries and PATH edits.

The owner explicitly asked that nothing leak into Windows, and floated moving the whole project
to CachyOS to avoid it — then chose to stay on Windows because that is where the PC actually
gets used. Windows also has to be the host regardless, because the server's entire purpose is
to report whether *this* Windows session is logged in.

Android Studio is not required to build an APK. The JDK, the SDK command-line tools and Gradle
all run headless.

## Decision

The Android toolchain lives in a Docker image, defined by `docker/Dockerfile`: JDK 21, SDK
command-line tools, platform 36. Builds run as

```bash
docker compose -f docker/compose.yml run --rm build ./gradlew assembleDebug
```

and the APK lands in a bind-mounted `out/`. Nothing Android-related is installed on the host.
Gradle caches live in a **named volume**, not a bind mount, because bind-mounting `/mnt/d`
through Docker Desktop is slow enough to be annoying.

## Consequences

- The host stays clean. `java -version` failing on Windows is a feature, and is an item on the
  manual verification checklist.
- The build is reproducible and the environment is code, which is worth something for a repo
  that becomes a portfolio piece.
- WSL2 and Docker Desktop must be installed — a real cost, though a general-purpose one, unlike
  a single-purpose IDE.
- **No IDE.** No debugger, no layout inspector. Acceptable for an app this size; VS Code with
  Java extensions covers editing.
- `adb` talking to the phone from inside a container is not something the Android docs cover.
  T7.2 settled it: `adb` stays on the host, and the recommendation is extracting
  `platform-tools` into `tools/` in the repo — a zip, no installer, and deleting the folder
  removes it completely.

## Alternatives considered

- **WSL2 without Docker** — lighter, but the setup lives in a script rather than an image, and
  is less reproducible.
- **Android Studio on Windows** — the well-trodden path, rejected on the grounds above.
