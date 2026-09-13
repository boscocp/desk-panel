# TT.10 — Login-scope verifier: pure-function tests

Size: S · Prereqs: T3.5 · Pairs with: T3.8, T3.9, T3.10 ·
Files: `server/tests/test_login_scope.py`, `server/tests/fixtures/login_scope/*`

Requires: none — that is the point

## Goal

Test all three platforms' login-scope checks on whichever machine you happen to be on, from
recorded output. This is what makes T3.10 partially verifiable with no Mac, and what stops the
Windows checks from rotting between the rare occasions someone runs them.

## Steps

1. Record fixtures — real output, captured once, committed:

   | Fixture | Good case | Trap case |
   |---|---|---|
   | `schtasks /XML` | `LogonTrigger`, `InteractiveToken`, `PT0S` | `MSFT_TaskTimeTrigger`; `Password` logon type; 72 h limit |
   | `systemctl --user show` | `WantedBy=graphical-session.target` + `PartOf=` | `WantedBy=default.target`, no `PartOf=` |
   | `loginctl show-user` | `Linger=no` | `Linger=yes` |
   | `launchctl print` | agent found in `gui/501` | "Could not find domain" |
   | plist | `LimitLoadToSessionType=Aqua` | `LoginWindow`, and the key absent |
   | `/proc/version` | ordinary kernel | contains `microsoft` (WSL) |

2. Assert each parser's verdict against each fixture. The `WantedBy=default.target` case must
   come back **not compliant** — that is the recorded intent in `docs/SERVER-SETUP.md` that
   [ADR 0010](../docs/adr/0010-login-signal-is-session-scoped.md) rejects, and it is the single
   most valuable assertion in this file.
3. Assert the auto-login detector on all three platforms' shapes, and the container detector on
   `/.dockerenv`.

## Acceptance

```bash
python -m unittest discover -s server/tests -t .
python server/verify_login_scope.py --self-test
```

## Notes

- No subprocess calls, no network, no sleeping. If a test needs a real `systemctl`, the parsing
  and the execution have not been separated properly — fix `verify_login_scope.py`, not the
  test.
