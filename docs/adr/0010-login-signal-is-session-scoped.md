# 0010 — The login signal is a graphical session, on every OS

Status: accepted · 2026-09-13 · Amends [0004](0004-server-is-login-signal-and-proxy.md)

## Context

[ADR 0004](0004-server-is-login-signal-and-proxy.md) established that the PC server *is* the
login signal: it answers only while a human is logged in, so the phone can hold its screen on
exactly then. It stated the rule in Windows vocabulary — "a Scheduled Task with an At-log-on
trigger, never a Windows Service" — because Windows was the only host.

Two things changed. Development moved to Linux, and the server should run on Linux and macOS as
well as Windows, with Windows remaining the day-to-day host.

Restating the rule per OS is not a translation exercise. The Windows sentence names one member
of a class, and the other members are not obvious:

- A systemd **system** unit is the direct equivalent of a Windows Service.
- A systemd **user** unit reached from `default.target` looks like a login trigger and is not.
  With `loginctl enable-linger` on — the state of this development machine today — the user
  manager starts at boot with nobody logged in and reaches `default.target`. The server would
  answer at the display-manager greeter. An **SSH** session reaches `default.target` too, even
  with lingering off.
- A macOS **LaunchDaemon** is the same mistake with a different filename; so is a LaunchAgent
  with `LimitLoadToSessionType` left unset, which loads at the login window.
- A **Docker container** is one as well, and this repo normalises `docker compose`
  ([ADR 0003](0003-containerized-toolchain.md)). `docker compose up` for the server would
  answer with nobody logged in at all.

`docs/SERVER-SETUP.md` had already written down the wrong Linux answer —
`WantedBy=default.target`, "carries the same semantics" — which would have broken the invariant
silently on the very machine development now happens on.

## Decision

The rule, stated without reference to any OS:

> The server is launched by, and dies with, the **graphical session of a specific human user**.
> It is never reachable from a supervisor of system scope, and never from a session that a
> human did not start by logging in at the screen.

The carriers, per OS:

| OS | Mechanism | The fields that are the invariant |
|---|---|---|
| Windows | Scheduled Task, current user | `LogonTrigger`; `LogonType = InteractiveToken`; `ExecutionTimeLimit = PT0S`; `DisallowStartIfOnBatteries = false` |
| Linux | systemd **user** unit | `WantedBy=graphical-session.target` **and** `PartOf=graphical-session.target`; `Type=exec` |
| macOS | LaunchAgent in `~/Library/LaunchAgents` | `LimitLoadToSessionType = Aqua`; `RunAtLoad = true` |

Three of those deserve their reason written down, because each looks optional and is not:

- **`PartOf=` on Linux.** `WantedBy=` starts the unit; it does not stop it. With logind's
  default `KillUserProcesses=no`, a `WantedBy`-only unit survives logout and keeps answering.
  `PartOf=` is what makes logging out mean something.
- **`ExecutionTimeLimit = PT0S` on Windows.** The default is 72 hours. Without it the server is
  killed on day four of an uptime streak, while the user is still logged in, and the panel goes
  dark for no visible reason.
- **`LimitLoadToSessionType = Aqua` on macOS.** Unset, the agent also loads in the
  `LoginWindow` and `Background` session types — answering at the login screen, which is the
  exact failure this ADR exists to prevent.

**Lingering is not required to be off.** Binding to `graphical-session.target` makes the
invariant hold regardless, which matters because linger is commonly on for unrelated reasons
(podman, pipewire, user timers). The acceptance proves the stronger property directly: the unit
is not in the transitive closure of `default.target`.

**Support tiers.** All three launchers are written and their shape checks pass on real
hardware: Windows, Linux, and macOS since wave 34 (`server/install_agent.sh`). Each is still
`blocked` on its behaviour half, a logout watched from a second device, because a task file whose
acceptance has not executed is a task file that lies.

## Consequences

- Three sibling installer tasks (T3.8 Windows, T3.9 Linux, T3.10 macOS) under one
  platform-neutral parent, T3.5, which owns the contract and the tools.
- Two stdlib tools make the invariant checkable: `server/probe.py`, which turns "answers" and
  "does not answer" into exit codes, and `server/verify_login_scope.py`, which fails if a
  system-scoped equivalent exists, if auto-login is on, or if it is running under WSL or in a
  container.
- The parsing in `verify_login_scope.py` is pure and fixture-driven (TT.10), so all three
  platforms' checks are tested on any one machine — including macOS, without a Mac.
- **Auto-login defeats this on every OS** and no launcher can fix it: the session starts with
  no human present, and the signal degrades to "the machine is powered on" — what ADR 0004
  rejects on its first page. It is detected and reported, not solved.
- Fast user switching means a second user's instance fails to bind while the first still
  answers. The panel then reads "logged in", which is true, just not about the owner. Accepted;
  the server must fail loudly rather than hang, so `allow_reuse_address` is off on Windows.
- **A starved server reads as a logout** (T4.7, 2026-10-01). The Scheduled Task's default
  priority is 7, which is BELOW_NORMAL, and with a game loading on the same PC `/ping` came back
  later than the phone's 1500 ms: the panel slept and woke six times in ninety seconds. The task
  is registered at priority 4 (NORMAL) and `verify_login_scope.py` fails anything outside 4–6.
  Not higher: a clock beside the monitor must not outrank its owner's own work. The phone also
  rides out one failed probe while online (`PcState.ONLINE_GRACE_FAILURES`), so one late answer
  from any cause is a missed poll and not a blink.

## Alternatives considered

**Windows-only, with a clean seam for later.** Rejected because the seam costs more than the
thing it defers. The server is stdlib HTTP and already portable; the only per-OS artefact is a
~30-line launcher. Meanwhile the portability work in T3.11 — UTF-8 on every `open()`,
cwd-independent config discovery, `allow_reuse_address` — fixes bugs that bite **Windows**
today, so it would be written either way.

**A polled heartbeat with a session-id, instead of process lifetime.** More code, another
failure mode, and it re-implements what three operating systems already do correctly.
