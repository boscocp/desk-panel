# TT.10 — Login-scope verifier: pure-function tests

Size: S · Prereqs: T3.5 · Pairs with: T3.8, T3.9, T3.10 ·
Files: `server/tests/test_login_scope.py`, `server/fixtures/login_scope/*`,
`server/verify_login_scope.py`

**The fixture path in the line above was wrong** and is corrected here: they live in
`server/fixtures/login_scope/`, not under `server/tests/`, because `verify_login_scope.py`
ships its own `--self-test` against them and a script has no business reaching into a test
directory to run.

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
   | ~~`loginctl show-user`~~ | ~~`Linger=no`~~ | ~~`Linger=yes`~~ |
   | `launchctl print` | agent found in `gui/501` | "Could not find domain" |
   | plist | `LimitLoadToSessionType=Aqua` | `LoginWindow`, and the key absent |
   | `/proc/sys/kernel/osrelease` | ordinary kernel | contains `microsoft` (WSL) |

   **Two rows were amended when this was done, and both are the implementation answering a
   better question than the table asked.**

   - **There is no linger fixture, because the verifier does not check lingering.** It proves
     the stronger property directly: the unit is not in the transitive closure of
     `default.target`. A unit outside that closure cannot be started by a lingering user
     manager at boot *or* by an SSH session, so the answer holds whatever `Linger` says —
     which is what lets T3.9's acceptance require it to pass **with `Linger=yes`**, this
     machine's current state. A `Linger=yes` fixture asserted against as a trap would have
     been a check that fails on a correct installation.
   - **WSL is read from `/proc/sys/kernel/osrelease`, not `/proc/version`.** Both carry the
     `microsoft` marker; osrelease is one short line containing nothing else, where
     `/proc/version` is a sentence that also names the compiler. Same evidence, no substring
     to be surprised by.

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

### Written while doing it

- **The purity rule is asserted, not promised.** `NothingRunsTests` nails `run_command`,
  `read_registry_autologin`, `read_file` and `file_present` shut and runs every case through
  again — and then asserts that doing the same to a *real* run does trip, so the guard cannot
  quietly stop guarding anything.
- **The cases are imported from `--self-test` rather than copied.** The module already had 96
  of them and the acceptance runs both commands; two lists of expectations for one parser
  drift, and the only thing worse than an unverifiable platform is two disagreeing accounts of
  what its output means. What this file adds on top is the assertions the table names by
  platform, stated as sentences a reader can check against ADR 0010 — plus one fixture the
  table asked for and nobody had recorded, a plist with `LimitLoadToSessionType=LoginWindow`.
- **Writing them found a real gap in the tests themselves**, which is the point of restating a
  self-test as named cases: `detect_autologin` dispatches on `sys.platform`, so the Windows
  branch answers to `"win32"` and not to `"windows"`. A test spelling it the readable way
  falls through to the Linux branch, finds no display manager, and returns `unknown` — not a
  pass, so it fails loudly, but it would have gone on asserting something true about the wrong
  platform if the expectation had been written to match what it returned.
