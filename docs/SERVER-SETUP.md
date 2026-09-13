# Server setup (Windows)

The server is one Python file using only the standard library. No pip, no virtualenv. It runs
on a clean Windows box with Python installed and nothing else.

## Configuration

```bash
cp server/config.example.json server/config.json
```

Edit it: tickers, city, brapi token, port. `config.json` is gitignored and never leaves the PC
— the token in particular must never reach the APK.

## Run it once by hand

```bash
python server/server.py
curl http://localhost:8777/ping
```

## Install the Scheduled Task

```powershell
powershell -ExecutionPolicy Bypass -File server\install_task.ps1
```

This registers a task with an **"At log on" trigger**, scoped to your user.

That trigger is the whole point: the task runs inside your session, so the server answering
means you are logged in. **Do not convert this into a Windows Service.** A service has the same
uptime and the wrong meaning — it would answer at the lock screen and before anyone logs in,
and the panel would light up for nobody.

## Firewall

Allow the port on the **Private** profile only:

```powershell
New-NetFirewallRule -DisplayName "desk-panel" -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 8777 -Profile Private
```

Never forward this port on the router. The server has no authentication because it is only ever
reachable from the LAN, and that assumption has to hold.

## Static IP

Reserve a fixed DHCP lease for the PC on your router.

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
curl http://<pc-ip>:8777/ping
```

A firewall prompt that never appears when testing locally will appear here. That is the point.

## Linux

`install_task.ps1` is Windows-only by nature. The Linux equivalent is a systemd **user** unit —
but bound to `graphical-session.target`, not `default.target`, and with `PartOf=` as well as
`WantedBy=`. Installed by `server/install_user_unit.sh` (T3.9).

This document used to recommend `WantedBy=default.target` and call it equivalent. It is not.
With `loginctl enable-linger` on, the user manager starts at boot with nobody logged in and
reaches `default.target`, so the server would answer at the greeter — the exact failure the
"never a Windows Service" rule exists to prevent. An SSH session reaches it too, even with
lingering off. `PartOf=` matters for the other end: without it the unit survives logout,
because logind defaults to `KillUserProcesses=no`.

Full reasoning in [ADR 0010](adr/0010-login-signal-is-session-scoped.md).

There is no firewall step here. Desktop distros usually ship no inbound filter, and when they
do it is firewalld *or* ufw *or* nftables — T3.9 detects and instructs rather than configuring.

## macOS

A LaunchAgent in `~/Library/LaunchAgents` with `LimitLoadToSessionType = Aqua` (T3.10). Never a
LaunchDaemon, and never `/Library/LaunchAgents`. Written but **unverified** — there is no Mac
to run it on, and the task is `blocked` rather than pretending otherwise.
