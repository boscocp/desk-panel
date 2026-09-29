# Security

## Reporting

Report privately: use GitHub's **Report a vulnerability** on this repository's Security tab, or
email **adalbertobosco@gmail.com**. Please do not open a public issue for anything in the first
list below. This is a one-person project, so expect an answer within a week, not within a day.

## What is in scope

This is a LAN appliance. The PC runs a small HTTP server; the phone polls it. The things worth
reporting are the ways that arrangement leaks or reaches further than it should:

- **The brapi token escaping.** It lives in the gitignored `server/config.toml` (or the legacy
  `config.json`) on the PC and must never reach git, the APK, a log line or any HTTP response
  ([ADR 0004](docs/adr/0004-server-is-login-signal-and-proxy.md)). A path by which it does is the
  most serious report this project can receive.
- **Signing material in the tree or the APK**: the keystore or its passwords, which live in the
  gitignored `.env` and `*.keystore`.
- **The server reaching past the LAN.** It binds `0.0.0.0` so the phone can reach it, and the
  firewall rule it documents is scoped to the private network. Anything that exposes it to the
  internet by default, or lets a request reach something other than the fixed routes, is in scope.
- **`POST /action/*` doing more than its catalogue.** The actions are a closed list of harmless,
  repeatable toggles ([ADR 0015](docs/adr/0015-the-panel-can-act-on-the-pc.md)). A request that
  runs anything else, passes an argument to a command, or gets past the `Origin` /
  `Sec-Fetch-Site` refusal from a browser is a vulnerability.
- **Cleartext widening.** The APK allows `http://` only to the PC addresses pinned at build time
  ([ADR 0016](docs/adr/0016-more-than-one-pc.md)). Anything that widens it is in scope.

## What is not

- **The server has no authentication.** That is a design decision for a home network the owner
  controls, argued in ADR 0004 and ADR 0015, not a vulnerability. On a network you do not control,
  set `actions = []`.
- Anyone on the LAN can read the quotes and the weather. They are public data.
- A phone or PC that is already compromised.
