# Server setup

The server is one Python file using only the standard library. No pip, no virtualenv. It runs
on a clean box with Python 3.11 or newer installed and nothing else.

Windows is the primary host and the one that is verified day to day; Linux and macOS follow the
same contract, stated per OS in [ADR 0010](adr/0010-login-signal-is-session-scoped.md). Whatever
the OS, the rule is the same one:

> The server is launched by, and dies with, the **graphical session of a specific human user**.
> It is never reachable from a supervisor of system scope, and never from a session that a human
> did not start by logging in at the screen.

That is not a preference about tidiness. The phone holds its screen on exactly while the server
answers, so anything that answers without a login — a Windows Service, a systemd **system**
unit, a LaunchDaemon, an `@reboot` entry, a Docker container, or a systemd **user** unit reached
from `default.target` — lights the panel for an empty room and looks like a phone bug.

## Configuration

```bash
cp server/config.example.toml server/config.toml
```

Edit that copy: tickers, city, brapi token, port. The copy also ships `latitude`/`longitude`,
which win over `city` for the weather: point them at your own street, or delete both to geocode
the city. `config.toml` is gitignored and never leaves the PC — the token in particular must
never reach the APK.

The copy has the two mute buttons on (`actions`). Anyone on the LAN can then press them, which
is harmless on a home network and the reason to set `actions = []` on one you do not control
([ADR 0015](adr/0015-the-panel-can-act-on-the-pc.md)).

**Read `config.example.toml` rather than this section.** It is written as documentation, not as
a sample: every key carries what it does, what its default is, and — the part that used to mean
reading `providers_brapi.py` — which values actually work. Which four B3 tickers answer without
a token, how an FX pair is spelled, which coins Binance quotes, and why the quotes interval is
600 seconds and not 300.

TOML rather than JSON because JSON cannot carry any of that: no comments, and a trailing comma
is a fatal error a page from where it was typed. TOML rather than YAML because the server is
standard-library-only (`server/CLAUDE.md`) and PyYAML is a dependency, while `tomllib` has
shipped with Python since 3.11.

### If you already have a `config.json`

Nothing to do. It is still read, exactly as before, and the server prints one line at startup
naming the replacement. Migrate when convenient, or not at all — but **how you migrate depends
on how the server is started**, because an explicit `--config` is never second-guessed. It names
its own file and its own format; only the fallback beside `server.py` chooses between the two
names.

**Started by hand, with no `--config`.** Copy the example, move your values across, delete the
old file. `config.toml` wins where both exist, so the switch happens the moment the new file is
there and deleting the old one is optional tidying.

**Started by the Scheduled Task** — which is every Windows install, since `install_task.ps1`
bakes an absolute `--config …\server\config.json` into the task action. Dropping a
`config.toml` next to it changes nothing, and *deleting* the `config.json` breaks the panel: the
server exits 1 at every logon, under `pythonw`, with no console to say why, and the phone
reports offline forever — indistinguishable from the DHCP-drift failure. So:

```powershell
copy server\config.example.toml server\config.toml   # then move your values across
powershell -ExecutionPolicy Bypass -File server\install_task.ps1
```

Re-running the installer re-registers the task against the config it now finds, `.toml` first.
Delete the old `config.json` only after that, and only once the panel has come back.

The same rule will apply to the systemd user unit and the LaunchAgent (T3.9, T3.10): whoever
passes the path is who has to change it.

## Calendars (optional)

The AGENDA card shows your next meeting from Google Calendar and Outlook (T9.1). This is off
until you list an account, and it is the one part of the panel that handles personal data, so
read [ADR 0017](adr/0017-calendars-are-personal-data.md) first. In short:

- **Read-only, primary calendar only.** Google `calendar.events.owned.readonly`, Microsoft
  `Calendars.ReadBasic`. The server refuses and discards any grant broader than that.
- **Tokens stay on this PC**, in `server/calendar-tokens.json` beside the config: gitignored,
  mode 0600, never in `config.toml`, never on the phone.
  - **On Windows, clone the repository inside your own profile** (`C:\Users\<you>\...`) and
    outside any folder OneDrive syncs. Mode bits do nothing there, so the file is exactly as
    private as the folder it sits in.
- **Titles are on by default, and anyone on your Wi-Fi can read them** at `/quotes`, for up to
  your next five events. Set `calendar_show_titles = false` and the card shows only the
  countdown.

You register your own OAuth client with each provider. Nobody ships a shared one.

### Google

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable
   the **Google Calendar API** for it.
2. Under **Google Auth Platform**, configure the consent screen with user type **External**, and
   add your own address as a test user.
3. Under **Data access**, add exactly one scope,
   `https://www.googleapis.com/auth/calendar.events.owned.readonly`.
4. Under **Clients**, create an OAuth client of type **Desktop app**. Copy its id and secret into
   `google_client_id` and `google_client_secret` in `config.toml`. Google's own documentation
   says a Desktop client's secret is "obviously not treated as a secret". It stays in the
   gitignored file anyway.
5. Under **Audience**, **publish the app** ("In production"). This step is not optional:
   - A consent screen left in "Testing" issues refresh tokens that **expire after 7 days**, and
     the card would say `reconnect` every week
     ([Google](https://developers.google.com/identity/protocols/oauth2)).
   - A published app nobody has verified is allowed for personal use by fewer than 100 users.
     You click through the "Google hasn't verified this app" warning once, at login.

Then list the account and connect it from this PC:

```toml
calendar_accounts = [{ provider = "google", name = "personal" }]
```

```bash
python server/calendar_login.py google --account personal
```

- **How it connects:** your browser opens Google's consent page, and the command catches the
  redirect on `127.0.0.1`, on a port the OS picks, and only for that one request.
- **Why not a short device code, as with Microsoft:** Google's device flow does not allow any
  Calendar scope.
- **On a PC without a browser:** add `--no-browser` and open the printed URL with an SSH tunnel
  to that port.

### Microsoft (personal and work or school)

1. In the [Microsoft Entra admin center](https://entra.microsoft.com/), go to **App
   registrations** and choose **New registration**.
   - For supported account types, choose **Accounts in any organizational directory and
     personal Microsoft accounts**.
   - No redirect URI is needed.
   - If the portal says you have no directory, a free Azure account creates one.
2. Under **Authentication**, set **Allow public client flows** to **Yes**. The device code flow
   needs it, and a public client has no secret to leak.
3. Under **API permissions**, choose **Add a permission**, then **Microsoft Graph**, then
   **Delegated**, and add **Calendars.ReadBasic**. It reads events without their body,
   attachments or extensions, and needs no admin consent. You can remove the default
   `User.Read`; the server accepts it, since it only reads your name.
4. Copy the **Application (client) ID** into `microsoft_client_id`.

```toml
calendar_accounts = [
    { provider = "microsoft", name = "personal" },
    { provider = "microsoft", name = "work" },
]
```

```bash
python server/calendar_login.py microsoft --account personal
python server/calendar_login.py microsoft --account work
```

Each command prints a URL and a short code. Open the URL on any device, type the code, and sign
in with the account you named. The command finishes by itself.

**A work or school account belongs to your employer's tenant, and the tenant decides.**

- The tenant may refuse consent to an app nobody there has approved. The sign-in then ends in
  an admin-consent request, and the account is not connected.
- Whether a work calendar may sit on a panel in your home is a question for your employer's
  data policy. This guide cannot answer it.

### Checking it, and undoing it

- `python server/server.py --check-only` names the configured accounts and the token file.
- A failing account is named on the card and in the server log, with the reason. The log never
  contains a token, a code or a title.
  - `microsoft/work: reconnect` means the grant is over: run the login again.
  - `unavailable` means the provider or the network is down, and it retries by itself.
- To disconnect, run `python server/calendar_login.py google --account personal --disconnect`.
  For Google this also revokes the grant. Microsoft has no per-app revocation endpoint, so
  remove the app yourself:
  - work or school: [My Apps](https://myapplications.microsoft.com/)
  - personal: [account.live.com/consent/Manage](https://account.live.com/consent/Manage)
- Google access can also be removed at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- Deleting `server/calendar-tokens.json` disconnects every account on this PC.

## Run it once by hand

```bash
python server/server.py
python server/probe.py --host 127.0.0.1 --expect up
```

`probe.py` rather than `curl`: in PowerShell `curl` is an alias for `Invoke-WebRequest`, which
does not understand `-sf` and exits 0 on flags it ignores. The probe behaves identically in
`cmd`, PowerShell, bash and fish, and turns the answer into an exit code — 0 when reality
matched `--expect`, 1 when it did not, 2 when the probe itself could not tell.

## Install the Scheduled Task

```powershell
powershell -ExecutionPolicy Bypass -File server\install_task.ps1
```

The config has to exist first: the installer runs `server.py --check-only` before it
registers anything, and stops with the copy command if it is missing.

This registers a task with an **"At log on" trigger**, scoped to your user.

That trigger is the whole point: the task runs inside your session, so the server answering
means you are logged in. **Do not convert this into a Windows Service.** A service has the same
uptime and the wrong meaning — it would answer before anyone logs in, and the panel would light
up for nobody.

Four settings carry that meaning and all four have the wrong default. The script states them
explicitly, then re-exports the task and asserts them, so a future PowerShell that changes one
fails the install instead of the panel:

| XML field | Value | What the default does instead |
|---|---|---|
| `LogonType` | `InteractiveToken` | `Password`/`S4U` run with no interactive session — a service in disguise |
| `ExecutionTimeLimit` | `PT0S` | 72 h, so the server dies on day four of an uptime streak, mid-session |
| `DisallowStartIfOnBatteries` | `false` | never starts on a laptop |
| `StopIfGoingOnBatteries` | `false` | stops the moment you unplug |

The cmdlets that produce them are spelled differently — `-LogonType Interactive`,
`-AllowStartIfOnBatteries`, `-DontStopIfGoingOnBatteries` — which is why every assertion in the
task file reads the exported XML rather than `Get-ScheduledTask`.

**Which Python ends up in the task** is the other thing the script is careful about. It resolves
the interpreter from the registry first, not from `PATH`: on a machine with any virtualenv
active, `python` — and `py`, which honours `VIRTUAL_ENV` — resolve into that environment, and a
task pointing there works until that unrelated project is deleted, then fails at the next login
with no console to say so. A Microsoft Store alias is rejected outright, for the same class of
reason: it opens the Store instead of starting the server. The script prints which source won.

Other switches: `-Python <path>` to pin the interpreter, `-NoStart` to register without
starting it, `-WhatIf` to see what it would do, and `-Uninstall` to remove the task — which
leaves the config file and the logs alone. Relative `-Config` and `-LogFile` are resolved
against your current directory and stored absolute, because the task itself runs with the
repository root as its working directory.

**Do not run the whole installer elevated to get the firewall rule.** It would re-register
the task for whichever account elevated: where the desk user is a standard user and UAC asks
for a separate administrator, the panel would then light when the admin logs in and never
when you do. Use `-FirewallOnly` from an elevated shell, which creates the rule and does not
touch the task at all. (`-Firewall` does both, and is only right when your own account is
the administrator.)

`pythonw` has no console, so the server's output goes to
`%LOCALAPPDATA%\desk-panel\server.log`. Read that first when the panel says offline and the task
says Running.

## Firewall

Allow the port on the **Private** profile only:

```powershell
New-NetFirewallRule -DisplayName "desk-panel" -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 8777 -Profile Private
```

Never forward this port on the router. The server has no authentication because it is only ever
reachable from the LAN, and that assumption has to hold.

**A Private rule only admits anything if the adapter is classified Private.** Windows classifies
unknown wired networks as Public, and then the rule above matches nothing: the phone reports
"offline" and it looks exactly like a server bug. Check it, and fix it once, elevated:

```powershell
Get-NetConnectionProfile
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

Do not widen the rule to the Public profile instead. LAN-only is the assumption the missing
authentication rests on. `install_task.ps1` reports both of these and creates neither on its
own; `-FirewallOnly`, from an elevated shell, creates the rule and nothing else.

## Static IP

Reserve a fixed DHCP lease for the PC on your router.

On this installation the PC is **192.168.15.3** on the `Ethernet` adapter, handed out by DHCP.
Until the router holds a reservation for it, that address is a loan, not a fact. The same value
goes into `PC_IP` in the gitignored `.env`, which is what stamps both the cleartext pin and the
dialled host into the APK at build time — the committed sources keep the placeholder
`192.168.1.100` on purpose (T7.3). Changing the address means rebuilding and reinstalling the
app, because cleartext permission is a property of the APK.

Ignore `192.168.56.1` if you see it: that is a VirtualBox host-only adapter, not the LAN.

`network_security_config.xml` in the app pins that address as the only one allowed to be
contacted over cleartext. If DHCP hands the PC a different address, the app reports "offline"
forever and looks exactly like a bug. This has to be done once and is easy to forget.

## BIOS: disable ErP Ready

Find *ErP Ready*, *EuP*, or *USB power in S5* and turn it **off**.

USB then loses power when the PC shuts down, so the phone discharges overnight and recharges
during the day instead of floating at 100% and warm around the clock. It is the single most
effective thing you can do for that battery, and it costs nothing — see
[DEVICE-CARE.md](DEVICE-CARE.md).

## Verifying

The real test is not `localhost`. Reboot, log in, wait a minute, then from **another device on
the LAN**:

```bash
python server/probe.py --host <pc-ip> --expect up
```

A firewall prompt that never appears when testing locally will appear here. That is the point.

Then **log out** — not lock — and probe again from the same device:

```bash
python server/probe.py --host <pc-ip> --expect down
```

Logging out must make it exit 0. If it does not, the launcher is of system scope and the panel
will stay lit with nobody there.

**Locked is not logged out.** An at-logon task keeps running while the screen is locked, and it
is supposed to: you are still logged in, you are still at the desk, and the panel should still
be lit. So locking must probe `--expect up`. The one that proves the invariant is the other
end — reboot and do *not* log in:

```bash
# reboot, do not log in, wait 90s
python server/probe.py --host <pc-ip> --expect down
```

Answering there is the failure that matters: it means the task has become a service. Run that
across a Fast Startup shutdown as well as a real reboot — hiberboot hibernates the kernel but
does log the user off, so the logon trigger still has to fire.

## Linux

`install_task.ps1` is Windows-only by nature. The Linux carrier is a systemd **user** unit,
rendered from `server/desk-panel.service.in` and installed by `server/install_user_unit.sh`
(T3.9) into `~/.config/systemd/user/`:

```bash
sh server/install_user_unit.sh              # install, enable, start
sh server/install_user_unit.sh --no-start   # install and enable; it starts at the next login
sh server/install_user_unit.sh --uninstall  # stop, disable, remove
```

It finds `python3` and the config for you — `server/config.toml`, then `server/config.json`,
then the same two under `~/.config/desk-panel/` — and writes both as **absolute** paths into the
unit, because a unit does not start in your shell's working directory. `--config PATH` overrides
the search, and `--python PATH` the interpreter.

Before it writes anything it refuses three installations that would each produce a server
answering with nobody at the desk, which is the one thing this design forbids:

- **as root, or under `sudo`.** That installs into root's user manager, where nothing starts it
  and where your own `systemctl --user` cannot see it.
- **beside a system-scoped `desk-panel` unit.** That one answers at boot; the user unit would
  then fail to bind the port for ever, and the panel would look perfect while reporting the
  wrong thing. Remove the system unit first.
- **where `graphical-session.target` is not active.** systemd does not start that target; the
  desktop does. GNOME, KDE and anything launched through
  [uwsm](https://github.com/Vladimir-csp/uwsm) do. A bare sway or i3 started from a TTY does
  not, and an enabled unit would sit there and never run — the panel permanently offline, with
  nothing in any log to say why.

Three fields in the unit are the invariant, and none of them is optional:

```ini
[Unit]
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=exec
ExecStart=/usr/bin/python3 -u /home/you/desk-panel/server/server.py --config /home/you/desk-panel/server/config.toml

[Install]
WantedBy=graphical-session.target
```

- **`WantedBy=graphical-session.target`**, never `default.target`. This document used to
  recommend `default.target` and call it equivalent. It is not. With `loginctl enable-linger`
  on — commonly switched on for unrelated reasons, podman or pipewire or user timers — the user
  manager starts at boot with nobody logged in and reaches `default.target`, so the server would
  answer at the greeter. An SSH session reaches it too, even with lingering off.
- **`PartOf=graphical-session.target`.** `WantedBy=` starts the unit; it does not stop it. With
  logind's default `KillUserProcesses=no`, a `WantedBy`-only unit survives logout and keeps
  answering. `PartOf=` is what makes logging out mean something.
- **`Type=exec`**, so systemd considers the unit started when the process is actually executing
  rather than merely forked. It does *not* wait for the socket — only `Type=notify` would — so
  `is-active` says the process is running and `probe.py` is what says the port is open.

Never `systemctl enable` without `--user`, never `sudo systemctl enable`, and never
`docker compose up` for the server. The toolchain is containerised (ADR 0003) and the reflex is
close at hand; a container answers with nobody logged in at all.

Lingering does **not** have to be off. Binding to `graphical-session.target` makes the invariant
hold either way, and the verifier below proves the stronger property directly: the unit is not
in the transitive closure of `default.target`.

### The firewall is detected, not configured

Desktop distros usually ship no inbound filter, and when they do it is firewalld *or* ufw *or*
nftables. The installer says which of the three is present and what the rule would be; it edits
nobody's security policy. Two things it cannot do for you:

- **read ufw's state, or nftables' ruleset, without root.** It says so rather than guessing —
  an installer that reported "no firewall" on a machine that has one would send you looking
  everywhere except at the thing that is blocking the phone. Run `sudo ufw status` yourself.
- **know where the phone is.** If the phone sits behind a router's NAT it is on a different
  subnet from this PC, and a rule scoped to the PC's own subnet will not let it in:

```bash
sudo ufw allow from <the phone's subnet> to any port 8777 proto tcp
```

Prove it from the phone's subnet, never from `localhost` — and pass `--port` if the config
moved it, because `probe.py` defaults to 8777 and a proof aimed at a closed port looks exactly
like a firewall:

```bash
python server/probe.py --host <this-pc-ip> --port 8777 --expect up
```

## macOS

A LaunchAgent in `~/Library/LaunchAgents` with `LimitLoadToSessionType = Aqua` (T3.10). Never a
LaunchDaemon, which loads at boot as root with nobody logged in, and never `/Library/LaunchAgents`,
which loads for *every* user's login.

```bash
cp server/config.example.toml server/config.toml     # then edit it
python3 server/server.py                             # once, in the foreground -- see below
sh server/install_agent.sh
```

The installer renders `server/dev.bosco.deskpanel.plist.in` with absolute paths, lints it, and
loads it into `gui/<uid>` with `launchctl bootstrap`. It refuses to run as root, beside a
LaunchDaemon or a `/Library/LaunchAgents` copy of the same label, or from a shell that is not in
the Aqua session (over SSH, say) unless you pass `--no-start`. Re-running it replaces the agent;
`--uninstall` removes it.

| | |
|---|---|
| status | `launchctl print gui/$(id -u)/dev.bosco.deskpanel` |
| restart | `launchctl kickstart -k gui/$(id -u)/dev.bosco.deskpanel` |
| log | `~/Library/Logs/desk-panel.log` |

**The interpreter must be 3.11 or newer**, and `/usr/bin/python3` on macOS is 3.9. Homebrew's
`python3` works. Homebrew does not install a bare `python`, which every command in this
repository uses; `/opt/homebrew/opt/python@3.13/libexec/bin` on your `PATH` provides it.

**The Application Firewall is per-binary, and the binary is not the one you think.** A framework
Python (Homebrew's, python.org's) re-execs into `…/Resources/Python.app/Contents/MacOS/Python`,
and that is what listens and what the firewall lists. The installer reads the running process
and names it. With the firewall on and no allowance, `/ping` answers on `127.0.0.1` and not
from the LAN, which looks exactly like a wrong IP. Allow it in System Settings → Network →
Firewall → Options; a `brew upgrade` moves the binary and the allowance has to be given again.
That is also why the server is run once in the foreground first: the "accept incoming network
connections" dialog wants a human, and under launchd it may never be seen.

Verified on macOS 26.5 (Apple Silicon) on 2026-09-29: `verify_login_scope.py` exits 0, `/ping`
and `POST /action/*` answer from the agent. **Not yet verified: that nothing answers at the
login window**, which needs a logout and a second machine (T3.10's behaviour block).

## Verifying the login scope

`probe.py` proves the server answers. It cannot prove *why* it answers, and a Windows Service
answers just as cheerfully as a Scheduled Task. `server/verify_login_scope.py` is the check for
the "why": run it on the host, as the user who owns the session.

```bash
python server/verify_login_scope.py
```

On the current OS it asserts that a session-scoped autostart entry exists and carries the fields
[ADR 0010](adr/0010-login-signal-is-session-scoped.md) names, that **no** system-scoped
equivalent exists alongside it, that auto-login is off, and that it is not running under WSL or
inside a container.

| Exit | Meaning |
|---|---|
| 0 | every check passed |
| 1 | at least one check failed — the invariant is broken on this machine |
| 2 | at least one check could not be determined |

**2 is not "probably fine".** A verifier that exits 0 when it could not look is worse than no
verifier, because what it exists to catch shows up as "the panel is lit while nobody is logged
in" — which nobody reads as a misconfigured launcher. So every check fails closed: a missing
command, an unreadable file or unexpected output all report *unknown*, never *pass*.

Auto-login is reported, not solved. No launcher can fix it: the session starts with nobody
present, and the signal degrades to "the machine is powered on" — which is what
[ADR 0004](adr/0004-server-is-login-signal-and-proxy.md) rejects on its first page.

Every check in that tool is a pure function over captured text, with the command execution in a
thin shell around it. So the parsers themselves can be checked anywhere, on any OS, against
real captured output in `server/fixtures/login_scope/`:

```bash
python server/verify_login_scope.py --self-test
```

That is how the macOS checks are tested without a Mac (TT.10). Since 2026-09-29 the macOS
fixtures for a loaded agent and an absent one are real captures from a Mac, and the first of
them found a parser bug that 97 green hand-written cases had not.
