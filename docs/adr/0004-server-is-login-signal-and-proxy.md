# 0004 — The PC server is both the login signal and the data proxy

Status: accepted · 2026-09-13 · Amended by [0010](0010-login-signal-is-session-scoped.md),
which restates the login-signal rule for Linux and macOS

## Context

The panel must appear when the PC is on **and logged in**, and disappear otherwise. The phone
cannot infer this from power: USB stays energised in S5, so `BatteryManager.charging` reads
`true` with the PC fully shut down. Any signal based on charging state is wrong from the start.

Separately, the panel needs quotes and weather. Weather (Open-Meteo) needs no key. Quotes
(brapi.dev) need a token for anything beyond four sample tickers, and a token compiled into an
APK is a token anyone can extract.

## Decision

A single small Python process on the PC does both jobs.

**As the login signal:** it is started by a Windows Scheduled Task with an "At log on" trigger,
so it runs inside the user's session. "It answers" therefore means "someone is logged in". A
Windows Service would answer before and without a login — the same uptime, the wrong meaning.

**As the data proxy:** `/quotes` and `/weather` call upstream on the server's behalf. The token
stays in `config.toml` on the PC, gitignored and never shipped.

## Consequences

- The signal is exactly the question being asked, with no inference.
- The token never reaches the phone.
- Tickers, city and refresh intervals become server config, so changing what the panel shows
  never requires rebuilding and reinstalling the APK. This is a bigger day-to-day win than it
  looks.
- The upstream provider can be swapped without touching Android code at all.
- Weather technically could be called straight from the device, but routing it through the same
  proxy keeps one code path instead of two. Uniformity wins here.
- **Accepted coupling:** no PC means no data. This costs nothing, because no PC also means the
  screen is asleep.
- The server is a dependency that must be running. `docs/SERVER-SETUP.md` covers the Scheduled
  Task, the firewall rule scoped to the Private profile, and the static DHCP reservation.

## References

- <https://learn.microsoft.com/en-us/windows/win32/taskschd/logon-trigger-example--xml->
- <https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule>
