# 0016 — The panel can follow more than one PC

Status: accepted · 2026-09-29 (T4.5)
Amends [ADR 0004](0004-server-is-login-signal-and-proxy.md) and
[ADR 0013](0013-local-configuration-boundaries.md), which assume exactly one PC and one
`PC_IP`.

## Context

The desk has two computers now: the Windows desktop the panel was built for, and a Mac on which
the server has run since wave 34 (T3.10). The APK allows cleartext to one address, fixed at build
time, and polls only that one. Following the Mac therefore meant rebuilding with the Mac's IP and
losing the Windows PC until the next rebuild. The owner asked for the panel to work with both.

Invariant 2 is what makes the question small. Each server is started by, and dies with, the
graphical session of its own human user. So "one of the listed PCs answers `/ping`" means
"someone is logged in at one of those screens", which is the fact the panel exists to show,
extended from one desk chair to two.

## Decision

- **`PC_IP` in `.env` is a comma-separated list.** One address is the old behaviour exactly.
  Every entry is range-checked like the single one was, and a bad one fails the build.
- **The cleartext pin lists each address by name.** The build turns the placeholder `<domain>`
  into one `<domain includeSubdomains="false">` per host inside the same `domain-config`. There
  is still no `base-config` and no manifest-wide flag. The pin widens by exactly the hosts
  listed and no further.
- **Online means some host answered.** `PcHosts` (plain Java, JVM-tested) keeps the list and the
  host that answered last. Each cycle asks that host first and stops at the first 200. While a PC
  is up, a cycle is one probe, as before. Offline, a cycle asks every host, so its worst case is
  N × 3 s.
- **Data and presses go to the host that answered last.** Both halves of a data cycle read it
  once, so a payload never pairs one PC's tickers with the other's city. Each PC keeps its own
  `server/config.toml`, and when the panel moves between PCs, what it shows moves too.
- **No flapping.** With both PCs on, the panel stays on the one it has until that one stops
  answering. A move is logged as plain text (`pc answered at <ip>`), not as a marker, because
  the state did not change.

## Consequences

- The screen sleeps only when **every** listed PC is away, which is the owner's intent. Anyone
  reading `state=online` in the log should now read it as "some listed PC".
- An offline cycle lasts longer with more hosts, and the dormancy ladder (T5.6) spaces offline
  cycles out, so the battery cost grows with the number of hosts, not with time. Two is the case
  measured; nothing tries to support ten.
- Every listed PC needs its own static DHCP reservation. One drifting address is no longer
  "offline for ever", but it is a PC the panel silently stops following, which is harder to
  notice.
- The address list is still build-time. Adding a PC is a rebuild and a reinstall, for the reason
  ADR 0013 gives: cleartext permission is a property of the APK.
