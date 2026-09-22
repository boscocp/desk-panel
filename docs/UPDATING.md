# Updating a machine after a pull

```bash
git pull
python scripts/after_update.py
```

That is the whole procedure. The script does the work and exits non-zero if anything is wrong,
so there is nothing to read carefully and nothing to remember. The rest of this page is why each
step is in it — read it when the script fails, not before.

| Exit | Meaning |
|---|---|
| 0 | every check this OS could run passed |
| 1 | something is really wrong — the panel may not be served the new code |
| 2 | something could not be determined; nothing in the report claims it is fine |

It never starts the server itself. On every OS it asks the launcher to, because the launcher is
the login signal (invariant 2): a process this script spawned would answer just as well and
would outlive the desktop, which is the one thing the design forbids.

## The failure this exists to prevent

A pull updates the *files*. The server answering the phone is a process started at your last
login, holding the code as it was then. Nothing restarts it.

On 2026-09-22 those were one minute apart: the Scheduled Task had started at 00:31:18, the pull
rewrote `server.py` at 00:32, and the phone — freshly reinstalled, asking for the moon and the
chance of rain — was served by a build that had never heard of either. `/ping` answered. The
panel was lit. `probe.py` would have exited 0. The two new cards were simply empty, and the
obvious suspects were all innocent: the APK was current, the config was fine, the tests were
green, the server was up.

So the check that matters is not "does it answer" but **"is what answers the code that is on
disk"**, and the script asserts it by importing the tree's own `normalise()`, asking it which
keys a weather payload should carry, and comparing that against the live response. When a field
is added to the payload the check starts requiring it without anybody editing this file.

## What the script does, in order

1. **`git`** — the HEAD it is about to act on, and whether the tree is dirty.
2. **`launcher`** — finds the Scheduled Task (Windows) or the systemd user unit (Linux) and
   reads the paths it was registered with. Everything downstream uses *those* paths, never a
   guess: the task bakes an absolute `--config`, and validating one file while the server reads
   another is not a check.
3. **`tests`** — the suites that need neither the phone nor the network. The Android suite needs
   Docker and is reported as skipped rather than silently dropped.
4. **`config`** — `server.py --check-only` against the config the launcher actually passes.
   This is the trap [SERVER-SETUP.md](SERVER-SETUP.md) spells out: a config that was moved or
   deleted makes the server exit 1 at every login, under `pythonw`, with no console to say why,
   and the phone reports offline forever — indistinguishable from the DHCP-drift failure.
5. **`restart`** — stop, **wait for the socket to actually close**, start, wait for it to open.
6. **`payload`** — `/weather` carries every key the tree's own code produces.
7. **`login scope`** — `verify_login_scope.py`: not that it answers, but *why* it answers.
8. **`apk`** — whether anything under `web/` or `android/` changed since the last clean run.

A red test suite does not block the restart, and that is deliberate. The new code is already on
disk and the next login will load it whatever the script does; the pull deployed it, the restart
only decides whether the phone waits until tomorrow. Failures are reported and still set the
exit code. A broken **config** does block it — that is the one thing that would stop the server
coming back up at all.

## A restart costs the caches, and the panel shows it

Every cache the server holds is in memory, so a restart empties all of them and the panel
degrades visibly for up to a minute. Both symptoms look like bugs and neither is:

- **The FX sparkline disappears.** Its series is fetched on `history_interval_s`, six hours by
  default, so until the first background refresh lands there is nothing to draw.
- **The moon's percentage changes.** A cold start answers from `providers_usno.synodic_phase()`
  — the arithmetic mean phase, `source: "mean"` — because the moon must never be `unknown` just
  because a network call is in flight. The USNO value replaces it moments later, and the two are
  a few points apart: 79% and 85% on the evening this was written.

Neither needs doing anything about, but do not restart three times in a row to watch it settle,
which is how this section came to be written. If somebody is looking at the panel, one restart
is the polite number.

## Windows

Nothing else to do. The Scheduled Task's action points at `server.py` inside the checkout, so a
pull updates what it will run and the task never needs re-registering for a code change.

Re-run `server\install_task.ps1` only when something the task *action* carries has to change:
the config path (see [SERVER-SETUP.md](SERVER-SETUP.md) on migrating to TOML — dropping a
`config.toml` beside a task that bakes `--config …config.json` is a silent no-op), the Python
interpreter, or the log file. A changed **port** needs the firewall rule, which is
`install_task.ps1 -FirewallOnly`.

**Do not stop and start the task back to back by hand.** `allow_reuse_address` is off on Windows
on purpose — so that a second server fails loudly instead of quietly serving half the requests —
so a start issued before the old process has let go of the socket dies with `WinError 10048` and
leaves *nothing* running. That is not a hypothetical; it is how this page came to exist. The
script waits for the socket in between, which is the whole reason to prefer it over two cmdlets.
A logout and login does the same job.

## Linux

Same command. It restarts the systemd user unit, which handles the socket handover itself —
`SO_REUSEADDR` is on everywhere except Windows, where it would let a second process steal
connections.

If the unit is not installed yet, the script says so: `sh server/install_user_unit.sh`. Running
the server by hand in a terminal works for a look, but it is not the login signal — it dies with
the terminal, not with the session.

## macOS

**Not implemented, and the script says so rather than guessing.** T3.10 is `blocked`: the
LaunchAgent plist ships and has never run on a Mac. When it does, the shape is already decided
by [ADR 0010](adr/0010-login-signal-is-session-scoped.md) — `~/Library/LaunchAgents`, with
`LimitLoadToSessionType = Aqua`, never a LaunchDaemon and never `/Library/LaunchAgents` — and
three things join the script:

- reading the agent's `ProgramArguments` for the registered paths, the way the Windows branch
  reads the task's action;
- `launchctl kickstart -k gui/$(id -u)/dev.bosco.desk-panel` as the restart, which is the
  launchd spelling of "ask the launcher, do not spawn it yourself";
- nothing about the socket wait, since macOS is POSIX here.

`verify_login_scope.py` already covers macOS from fixtures (TT.10), so the check that the agent
is session-scoped and has no LaunchDaemon twin works before any Mac exists.

## The APK is the other half

The server restart cannot touch what the phone renders. `web/` is packaged as APK assets and
`android/` is the app, so a change under either needs:

```bash
make apk            # docker compose -f docker/compose.yml run --rm build ./gradlew assembleDebug
adb install -r out/desk-panel-debug.apk
```

The script reports this against the last commit it saw run cleanly on this machine, recorded in
`.after-update-state.json` (gitignored, per machine). The first run has no reference point and
says so instead of claiming a verdict. It is a proxy for "what is installed on the phone", which
the repo cannot know — if you rebuild without running the script, or run the script without
rebuilding, the proxy drifts and only a reinstall settles it.
