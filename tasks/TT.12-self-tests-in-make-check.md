# TT.12 — The self-tests nothing runs

Size: S · Prereqs: TT.9 · Pairs with: T3.13 · Files: `scripts/after_update.py`, `Makefile`

Requires: nothing beyond a checkout

## Goal

`python scripts/after_update.py --self-test` exits 1 on Linux, has done since it was
written, and no target runs it — so nothing went red.

## The finding, which is the shape and not the two cases

Two cases fail on a POSIX box:

```
FAIL  python_for: pythonw.exe -> python.exe, same directory
FAIL  python_for: case does not matter on Windows
```

`python_for` uses `Path`, which is `PosixPath` here, so `Path(r"C:\Python313\pythonw.exe").name`
is the whole string and the function returns it unchanged. Correct on Windows, untestable on
Linux. The fix is `PureWindowsPath` on the Windows branch, which `verify_login_scope.py` already
learned in T3.8: *"`check_macos_agent` tested `"/Library/LaunchAgents/" in str(path)` and a
`WindowsPath` stringifies with backslashes, so the macOS row silently failed on the primary
platform."* Same defect, mirrored.

**The shape is the finding.** Wave 20 found the server suite had been red on Windows since
wave 18 because both waves were judged on Linux. Wave 22 found this script red on Linux because
it was judged on Windows. Neither direction is caught by the loop — only by whoever happens to
run the other OS. A self-test no target invokes is a test suite with no runner.

TT.9 wired its own `--self-test` into `make lint-workflow` for exactly this reason. This task
does the same for the one that predates it.

## Steps

1. `python_for` (and anything else in `after_update.py` deciding about Windows paths) uses
   `PureWindowsPath` for the Windows branch and `PurePosixPath` for the POSIX one, never the
   platform-bound `Path`. A pure path class has no filesystem behind it and therefore no
   opinion about which OS is running.
2. Grep the other scripts for the same defect before declaring it fixed: any `Path(...)` whose
   argument is a Windows string, or whose result is compared against a Windows separator, is
   the same bug wearing a different name.
3. A Makefile target runs every `--self-test` in `scripts/`, and `check` depends on it. Find
   them by globbing rather than by listing, so the next script to grow one is covered by being
   written.
4. `docs/harness-notes/` is not the place for this; `docs/LEARNING-REPORT.md` is, if the
   cross-platform pattern is worth a paragraph by then.

## Acceptance

```bash
python scripts/after_update.py --self-test
python scripts/check_workflow.py --self-test
make lint-selftests
python - <<'PY'
import pathlib, re, sys
# Every script carrying a --self-test flag is reached by the new target.
scripts = [p.name for p in pathlib.Path("scripts").glob("*.py")
           if "--self-test" in p.read_text(encoding="utf-8")]
recipe = re.search(r"^lint-selftests:\n((?:\t.*\n)+)", pathlib.Path("Makefile").read_text(),
                   re.M)
sys.exit(0 if recipe and scripts and all(s in recipe.group(1) or "glob" in recipe.group(1)
                                         for s in scripts) else 1)
PY
make check
```

The fourth line is the one that matters: it fails if a script grows a `--self-test` that the
target does not reach, which is the defect this task exists to close rather than the two
failing cases.

## Notes

- Found on `main` during wave 22 (T3.6 + T7.2) and recorded in `tasks/STATUS.md` under
  *"Found on `main`, not fixed here, and it needs a row"*. This is that row.
- `after_update.py` is T3.13's. Changing its pure functions is in scope here; changing what it
  does to a running installation is not.
- **A second one, found the same way while TT.9 was being written.**
  `python scripts/check_status.py` also exits 1 on `main`, and has for some time:

  ```
  T9.1-next-event.md: prereq ADR does not exist
  T9.2-voice-assistant-spike.md: prereq ADR does not exist
  ```

  Both files carry `Prereqs: T8.2, ADR 0015`, and an ADR is a perfectly good prerequisite —
  `check_status` simply reads every comma-separated item as a task id. So the script is wrong,
  not the task files, and it went unnoticed for the same reason as everything else in this
  task: `make check` runs `check_acceptance`, `check_harness_notes` and
  `check_permission_parity`, and not this one. Teach it `ADR NNNN`, then add it to the target
  in step 3 — the two fixes are the same fix.
