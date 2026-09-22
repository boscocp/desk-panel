# TT.11 — The unit-rendering test skips the shell that cannot run it

Size: S · Prereqs: T3.9 · Files: `server/tests/test_unit_rendering.py`

Requires: nothing. The point of the change is that it needs *less* than before.

**Found by T3.13**, which runs the server suite as one of its steps and reported
`FAILED (failures=8)` on a clean `main`. `make check` was red on the primary host and had been
since wave 18 landed.

## What was actually wrong, after two wrong answers

The eight failures were all `test_unit_rendering`: every hostile path (`&`, `|`, `\`, and all
three at once) came back from `sed_escape` unescaped.

That reads as the escaping being broken for the third time — the file's own docstring says it
has been wrong twice already. It is not. Read out of `install_user_unit.sh` and run through
`sed -f`, which involves no argument passing at all, the shipped expression is provably correct:

    bytes: s/[\\&|]/\\&/g
    x&y -> x\&y      x|y -> x\|y      x\y -> x\\y

**It is the transport.** Git Bash on Windows hands arguments to a native `sed.exe` through
MSYS2's argument conversion, one backslash is eaten on the way, and the same expression that
works under `sed -f` escapes nothing when passed as `-e`. Reaching that took three wrong
reproductions, each mangled by a different quoting layer — including the agent's own shell,
which collapsed `\\` in the commands written to diagnose it. Only reading the bytes out of the
file settled it.

`install_user_unit.sh` installs a systemd unit. It never runs on Windows, and nothing is going
untested in production.

## Goal

The suite is green on every host, and still fails on Linux if the escaping ever breaks.

## Steps

1. **`shell_passes_backslash_to_sed()`**, checked in `setUpClass`. It hands `sed` a fixed
   `s/x/\\y/` and requires `\y` back. Eat one backslash in transit and the replacement reads
   `\y`, which yields a bare `y`, and the probe fails.

2. **The probe must not go through `sed_escape`, and that is the whole design.** A skip keyed on
   "the escaping looks wrong" would mask exactly the two bugs this file was written after — it
   would have gone green for both of them. The probe's expression is fixed and its expected
   answer is fixed, so a genuinely broken `sed_escape` still runs and still fails.

3. **Detected, never assumed from `sys.platform`.** A platform check would be a guess about
   which shells mangle arguments, and it would skip a WSL or Cygwin box that is perfectly able
   to run this. It would also lie in the other direction the day MSYS2 fixes it.

4. **`skipTest`, not a silent pass.** The reason names the cause and where the coverage does
   live, so a green run on Windows does not read as a proof it is not.

## Acceptance

```bash
python -m unittest server.tests.test_unit_rendering
python -m unittest discover -s server/tests -t .
python scripts/check_acceptance.py
python -c "import inspect, sys; sys.path.insert(0,'.'); from server.tests import test_unit_rendering as m; sys.exit(0 if 'sed_escape(' not in inspect.getsource(m.shell_passes_backslash_to_sed) else 1)"
! grep -q "sys.platform" server/tests/test_unit_rendering.py
python -c "import sys; sys.path.insert(0,'.'); from server.tests.test_unit_rendering import shell_passes_backslash_to_sed as p; sys.exit(0 if isinstance(p(), bool) else 1)"
```

The fourth line is the one that matters: it asserts the probe never calls the function under
test, which is the property that keeps this a skip rather than a blindfold.

## Notes

- **The failure was invisible to every wave that shipped it.** Wave 18 wrote the test, wave 19
  merged on top of it, and both were judged on Linux where it passes. Nothing in the loop runs
  the server suite on the Windows host except a human doing it by hand — which is precisely the
  gap `scripts/after_update.py` closes as a side effect of its own job.
- The test is skipped on this desk, so **the escaping itself is unverified here**. It is
  verified on Linux, and the CachyOS box is where `install_user_unit.sh` actually runs.
