#!/usr/bin/env python3
"""What to do on this machine after pulling an update. One command, no thinking.

    python scripts/after_update.py              # do it
    python scripts/after_update.py --dry-run    # say what it would do, touch nothing
    python scripts/after_update.py --rebuilt    # the APK on the phone is this commit
    python scripts/after_update.py --self-test  # check the pure functions, no machine

The problem this exists to solve is not "restart the server". It is that a pull
updates the *files* while the server that answers the phone is a process started
at your last login, holding the code as it was then. On 2026-09-22 those were one
minute apart: the task had started at 00:31:18, the pull rewrote `server.py` at
00:32, and the phone -- freshly updated, asking for the moon and the chance of
rain -- was served by a build that had never heard of either. Nothing was broken.
Nothing looked broken. The two new cards were simply empty.

So the order here is deliberate: prove the tree is sound, prove the config the
launcher actually passes still parses, restart in a way that cannot race itself,
then prove the process now answering is running the code that is on disk.

Stdlib only, like the rest of this repo (`server/CLAUDE.md`). Python 3.11+.

**It never starts the server directly.** On every OS it asks the launcher to do
it, because the launcher is the login signal (invariant 2): a `pythonw` this
script spawned would answer just as well and would outlive the desktop, which is
the one thing the whole design forbids. See
docs/adr/0010-login-signal-is-session-scoped.md.

Exit codes, the same three `verify_login_scope.py` uses and for the same reason:

  0  every check this OS could run passed
  1  something is really wrong -- the panel is not being served the new code
  2  something could not be determined; nothing here claims it is fine

Usage:
  python scripts/after_update.py [--dry-run] [--self-test] [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

REPO_ROOT = Path(__file__).resolve().parent.parent

# Both hardcoded, and both have to stay in step with the installers:
# install_task.ps1 pins the same task name (and says why a renamed task would
# make verify_login_scope.py report "not installed" about a healthy box), and
# install_user_unit.sh pins the unit name.
TASK_NAME = "desk-panel"
UNIT_NAME = "desk-panel.service"

# Where the last successful run is recorded, so "changed since you last ran
# this" is an exact statement rather than a guess. Gitignored: it is per
# machine, and two machines pulling the same commit have rebuilt different
# things.
STATE_FILE = REPO_ROOT / ".after-update-state.json"

# A change under either of these cannot reach the panel without a new APK:
# `web/` is packaged as assets (android/app/build.gradle.kts points
# assets.srcDirs at it), and `android/` is the app itself. Everything else --
# server, config, tasks, docs -- is picked up by the restart below.
REBUILD_PREFIXES = ("web/", "android/")

PASS, FAIL, UNKNOWN, SKIP = "pass", "fail", "unknown", "skip"

MARKS = {PASS: "ok  ", FAIL: "FAIL", UNKNOWN: "??  ", SKIP: "--  "}


class Step:
    """One check, its verdict, and one line a human can act on."""

    def __init__(self, name, status, detail=""):
        self.name = name
        self.status = status
        self.detail = detail

    def __repr__(self):  # pragma: no cover - diagnostics only
        return f"Step({self.name!r}, {self.status!r}, {self.detail!r})"


# --------------------------------------------------------------------------
# Pure functions. Everything that decides anything lives here, so --self-test
# can cover it on a box with no Scheduled Task, no systemd and no Mac -- the
# same split server/CLAUDE.md asks of the request handler.
# --------------------------------------------------------------------------


def parse_task_arguments(arguments):
    """Pull `{server_py, config, log_file}` out of a Scheduled Task's argument
    string.

    The task action is one flat string, built by install_task.ps1 as

        "<server.py>" --config "<config>" --log-file "<log>"

    and every one of those paths can contain spaces -- the default Python lives
    under `C:\\Program Files`. So this reads quoted runs, never `.split()`.

    Returns None for anything it cannot recognise rather than a half-filled
    dict: acting on a guessed config path is how you validate one file and
    restart a server reading another.
    """
    if not arguments:
        return None
    quoted = re.findall(r'"([^"]*)"', arguments)
    if not quoted:
        return None
    found = {"server_py": quoted[0], "config": None, "log_file": None}
    for flag, key in (("--config", "config"), ("--log-file", "log_file")):
        match = re.search(rf'{flag}\s+"([^"]*)"', arguments)
        if match:
            found[key] = match.group(1)
    if found["config"] is None:
        # A task with no --config is a task reading whatever sits beside
        # server.py, which is legal (config_search_paths) but is not something
        # this script should infer on a machine it is about to restart.
        return None
    return found


def parse_exec_start(unit_text):
    """`{python, server_py, config}` out of a systemd unit's `ExecStart=`, or None.

    The Linux sibling of `parse_task_arguments`, and it exists for the same
    reason: without it the Linux branch had a launcher and no config, so it
    never reached a port, never reached the restart, and `restart_linux` was
    unreachable code while the docs claimed it ran. Found by review.

    `desk-panel.service.in` quotes all three paths -- systemd splits a command
    line on whitespace, so a checkout under `~/My Projects` needs them -- which
    is why this reads the unit **file** rather than `systemctl show -p
    ExecStart`. That prints `argv[]=` space-separated with the quoting already
    resolved, so a path with a space in it comes back indistinguishable from two
    arguments.
    """
    match = re.search(r"^ExecStart=(.*)$", unit_text or "", re.MULTILINE)
    if match is None:
        return None
    quoted = re.findall(r'"([^"]*)"', match.group(1))
    config = re.search(r'--config\s+"([^"]*)"', match.group(1))
    if len(quoted) < 2 or config is None:
        return None
    return {"python": quoted[0], "server_py": quoted[1], "config": config.group(1)}


def unit_file_path():
    """Where `install_user_unit.sh` writes the unit, same rule it uses."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / UNIT_NAME


def _pure(path_str):
    """A pure path in the flavour the string is written in.

    Pure path classes have no filesystem behind them and therefore no opinion
    about which OS is running, which is the whole point: a function that reasons
    about a Windows path must behave the same when a Linux runner reads it.

    A drive letter or a backslash means Windows. Nothing else does -- a bare
    `pythonw.exe` has no separator at all and either flavour answers alike.
    """
    if re.match(r"^[A-Za-z]:[\\/]", path_str) or "\\" in path_str:
        return PureWindowsPath(path_str)
    return PurePosixPath(path_str)


def python_for(pythonw):
    """`python.exe` beside a `pythonw.exe`, or the path unchanged.

    The task deliberately runs `pythonw` -- no console window at login -- but
    `--check-only` exists to *print* a complaint, and under `pythonw` that
    complaint goes nowhere. install_task.ps1 makes the same swap for the same
    reason.

    Returned unchanged when it is not a `pythonw`, and *unchanged* is literal:
    `str(Path("/usr/bin/python3"))` is `\\usr\\bin\\python3` on Windows, so
    round-tripping a path this function does not mean to touch would corrupt it.

    The flavour comes from **the string**, never from the OS running this. `Path`
    is platform-bound, so on Linux `Path(r"C:\\Py\\pythonw.exe").name` is the whole
    string, nothing matches, and the swap silently does not happen -- correct on
    Windows and wrong everywhere else, which is why the two self-test cases below
    were red on Linux from the day they were written. `verify_login_scope.py` hit
    the mirror image of this in T3.8, where a `WindowsPath` stringified with
    backslashes and the macOS check failed on the primary platform.
    """
    path = _pure(pythonw)
    if path.name.lower() == "pythonw.exe":
        return str(path.with_name("python.exe"))
    if path.name.lower() == "pythonw":
        return str(path.with_name("python"))
    return pythonw


def needs_rebuild(changed_paths):
    """The subset of `changed_paths` that cannot reach the panel without a new APK.

    Repo-relative, forward slashes -- `git diff --name-only` spells them that
    way on every OS.
    """
    return sorted(
        p for p in changed_paths if any(p.startswith(prefix) for prefix in REBUILD_PREFIXES)
    )


def overall_exit(steps):
    """0, 1 or 2 from a list of Steps: any failure is 1, else any unknown is 2.

    Failure outranks unknown deliberately. A run that both failed a check and
    could not read another is a broken machine, and reporting 2 there would
    file it under "have a look sometime".
    """
    if any(step.status == FAIL for step in steps):
        return 1
    if any(step.status == UNKNOWN for step in steps):
        return 2
    return 0


def expected_weather_keys(has_moon):
    """The keys `/weather` must carry for the tree's own code to be the code serving it.

    Derived from the repo, never hardcoded: `normalise` is imported and asked.
    That is the whole trick -- next time a field is added to the payload this
    check starts requiring it without anybody remembering to edit this file,
    and a server left running on yesterday's code fails it.
    """
    from server.providers_openmeteo import normalise

    sample = normalise(
        {
            "current": {"time": "2026-09-22T00:00", "weather_code": 2, "is_day": 1},
            "daily": {
                "time": ["2026-09-22"],
                "temperature_2m_max": [26.0],
                "temperature_2m_min": [15.0],
                "precipitation_probability_max": [98],
            },
        }
    )
    keys = set(sample)
    if has_moon:
        # The moon rides inside the weather object rather than in its own
        # endpoint (server.py: "a forecast outage must not take the moon with
        # it"), so its absence from a live response is a stale server, not a
        # missing feature.
        keys.add("moon")
    return keys


def format_report(steps):
    """The run, one line per step, aligned."""
    width = max((len(step.name) for step in steps), default=0)
    lines = []
    for step in steps:
        line = f"  {MARKS[step.status]}  {step.name.ljust(width)}"
        if step.detail:
            line = f"{line}  {step.detail}"
        lines.append(line.rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The thin layer that touches the machine.
# --------------------------------------------------------------------------


def run(command, cwd=None, timeout=300):
    """Run `command` (a list), capture everything, never raise."""
    try:
        done = subprocess.run(
            command,
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except FileNotFoundError:
        return None, f"{command[0]}: not found"
    except subprocess.TimeoutExpired:
        return None, f"{command[0]}: timed out after {timeout}s"
    except OSError as exc:
        return None, f"{command[0]}: {exc}"


def powershell(script, timeout=120):
    """One PowerShell command, with the profile out of the way.

    Windows state is read through the ScheduledTasks cmdlets rather than
    `schtasks`, and that is not a style choice. This machine is pt-BR: T3.8
    found `reg query` printing `ERRO:` where the parser expected `ERROR:`, and
    `schtasks /query /fo list` localises both the field names and the status.
    `(Get-ScheduledTask).State` is an enum -- it says `Running` and `Ready` in
    every locale.
    """
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


def port_is_listening(port, host="127.0.0.1", timeout=1.0):
    """True if something accepts a TCP connection on `port` right now."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(port, listening, timeout, interval=0.3):
    """Block until the port is (or is not) accepting, or `timeout` runs out.

    Returns True if the wanted state arrived. This is the function that stops
    the restart racing itself: `allow_reuse_address` is off on Windows on
    purpose -- so that a second server fails loudly instead of quietly serving
    half the requests -- which means a start issued before the old process has
    let go of the socket dies with WinError 10048 and leaves nothing running at
    all. Stop, wait for the socket to actually close, then start.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_listening(port) == listening:
            return True
        time.sleep(interval)
    return port_is_listening(port) == listening


def git(args):
    code, output = run(["git"] + args)
    return code, output.strip()


def read_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Per-OS launcher handling.
# --------------------------------------------------------------------------


def windows_task():
    """`(action, state)` for the installed task, or `(None, reason)`.

    `action` carries Execute/Arguments as install_task.ps1 registered them, read
    as JSON so no output parsing is involved.
    """
    code, output = powershell(
        f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction Stop; "
        "$a = @($t.Actions)[0]; "
        "[pscustomobject]@{ state = [string] $t.State; execute = $a.Execute; "
        "arguments = $a.Arguments } | ConvertTo-Json -Compress"
    )
    if code is None:
        return None, output
    if code != 0:
        return None, f"no Scheduled Task named '{TASK_NAME}' (run server/install_task.ps1)"
    try:
        # ConvertTo-Json on a single object is one JSON object; the last
        # non-empty line is it, since a warning could precede it.
        payload = json.loads([ln for ln in output.splitlines() if ln.strip()][-1])
    except (ValueError, IndexError):
        return None, "could not read the task's action as JSON"
    return payload, payload.get("state", "")


def restart_windows(port, timeout, dry_run):
    """Stop, wait for the socket, start, wait for the socket. Returns a Step."""
    if dry_run:
        return Step(
            "restart",
            SKIP,
            f"would stop '{TASK_NAME}', wait for :{port} to close, start it again",
        )

    code, output = powershell(f"Stop-ScheduledTask -TaskName '{TASK_NAME}'")
    if code is None:
        return Step("restart", UNKNOWN, output)
    if code != 0:
        # Without this the refused stop fell through to the socket wait, which
        # timed out on the server that was still running and blamed "something
        # else owns it" -- a cause that is not the cause, with the actual error
        # discarded. Found by review; the start below always checked its code.
        return Step("restart", FAIL, f"could not stop the task: {output.strip()[:200]}")

    if not wait_for_port(port, listening=False, timeout=timeout):
        # Something is still holding it. Starting now would be the 10048 that
        # takes down the survivor too, so refuse rather than make it worse.
        return Step(
            "restart",
            FAIL,
            f"port {port} still accepting {timeout}s after the stop -- something "
            f"else owns it (a hand-started server?). Nothing was started.",
        )

    code, output = powershell(f"Start-ScheduledTask -TaskName '{TASK_NAME}'")
    if code is None or code != 0:
        return Step("restart", FAIL, f"could not start the task: {output.strip()[:200]}")

    if not wait_for_port(port, listening=True, timeout=timeout):
        return Step(
            "restart",
            FAIL,
            f"started, but nothing answers on :{port} after {timeout}s -- check the log",
        )
    return Step("restart", PASS, f"task restarted, answering on :{port}")


def restart_linux(port, timeout, dry_run):
    if dry_run:
        return Step("restart", SKIP, f"would run: systemctl --user restart {UNIT_NAME}")
    code, output = run(["systemctl", "--user", "restart", UNIT_NAME], timeout=60)
    if code is None:
        return Step("restart", UNKNOWN, output)
    if code != 0:
        return Step("restart", FAIL, f"systemctl restart failed: {output.strip()[:200]}")
    if not wait_for_port(port, listening=True, timeout=timeout):
        return Step("restart", FAIL, f"unit restarted but nothing answers on :{port}")
    return Step("restart", PASS, f"unit restarted, answering on :{port}")


# --------------------------------------------------------------------------
# The run.
# --------------------------------------------------------------------------


def step_git_state():
    code, head = git(["rev-parse", "--short", "HEAD"])
    if code != 0:
        return Step("git", UNKNOWN, "not a git checkout?"), None
    _, dirty = git(["status", "--porcelain"])
    if dirty:
        count = len(dirty.splitlines())
        return Step("git", PASS, f"HEAD {head}, {count} uncommitted file(s)"), head
    return Step("git", PASS, f"HEAD {head}, clean"), head


def step_tests():
    """The suites that need neither the phone nor the network.

    Not `make check`: there is no `make` on the Windows host (and putting one
    there would break the "keep the host clean" requirement of ADR 0003 by the
    same argument that keeps the JDK out). The Android suite needs Docker and is
    reported as skipped rather than silently dropped.
    """
    steps = []
    code, output = run([sys.executable, "-m", "unittest", "discover", "-s", "server/tests", "-t", "."])
    if code is None:
        steps.append(Step("tests: server", UNKNOWN, output))
    else:
        tail = output.strip().splitlines()[-1] if output.strip() else ""
        steps.append(Step("tests: server", PASS if code == 0 else FAIL, tail[:120]))

    code, output = run(["node", "--test", "web/test/**/*.test.js"])
    if code is None:
        steps.append(Step("tests: web", SKIP, "no node on PATH"))
    else:
        # The failing line, not a bare FAIL: a report that says only "node
        # --test failed" sends you off to run it again by hand, which is the
        # opposite of this file's whole point. Found by review.
        fails = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("not ok")]
        detail = fails[0][:120] if fails else ""
        steps.append(Step("tests: web", PASS if code == 0 else FAIL, detail))

    steps.append(Step("tests: android", SKIP, "needs Docker -- make test-android"))
    return steps


def step_config(python_exe, config_path, server_py):
    """`--check-only` on the config the launcher actually passes.

    This is the trap SERVER-SETUP.md spells out: the task bakes an absolute
    `--config`, so a config that was moved or deleted makes the server exit 1 at
    every login, under `pythonw`, with no console to say why -- and the phone
    reports offline forever, which looks exactly like the DHCP-drift failure.
    Better to find it here than at the next login.
    """
    if not Path(config_path).is_file():
        return Step("config", FAIL, f"the launcher passes {config_path}, which does not exist")
    code, output = run([python_exe, server_py, "--check-only", "--config", config_path])
    if code is None:
        return Step("config", UNKNOWN, output)
    if code != 0:
        return Step("config", FAIL, output.strip().splitlines()[-1][:160] if output.strip() else "")
    notice = [ln for ln in output.splitlines() if ln.startswith("notice:")]
    return Step("config", PASS, notice[0][:160] if notice else Path(config_path).name)


def step_payload(port):
    """Prove the process now answering is running the code that is on disk.

    The one check that would have caught 2026-09-22 before the phone did.
    """
    import urllib.error
    import urllib.request

    sys.path.insert(0, str(REPO_ROOT))
    try:
        has_moon = (REPO_ROOT / "server" / "providers_usno.py").is_file()
        expected = expected_weather_keys(has_moon)
    except Exception as exc:  # the tree is what it is; say so rather than guess
        return Step("payload", UNKNOWN, f"could not read the expected keys: {exc}")

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/weather", timeout=30) as response:
            live = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Step("payload", FAIL, f"/weather did not answer: {exc}")

    missing = sorted(expected - set(live))
    if missing and live.get("stale"):
        # The restart emptied the cache, so this call is the first fetch. If it
        # failed, `App.weather` answers from a five-key fallback -- no `isDay`,
        # no `precipProb` -- and the keys are missing for a reason that has
        # nothing to do with which code is running. Calling that "older code"
        # would be a confident wrong answer about the one condition this script
        # exists to detect. Found by review.
        return Step(
            "payload",
            UNKNOWN,
            f"/weather is stale and missing {', '.join(missing)} -- the cache is cold or "
            f"upstream is down, so this cannot tell which code is running. Run it again.",
        )
    if missing:
        return Step(
            "payload",
            FAIL,
            f"/weather is missing {', '.join(missing)} -- the server is running older code",
        )
    return Step("payload", PASS, f"{len(expected)} expected key(s) present")


def step_login_scope(python_exe):
    """`verify_login_scope.py`: not *that* it answers, but *why* it answers."""
    code, output = run([python_exe, "server/verify_login_scope.py"])
    if code is None:
        return Step("login scope", UNKNOWN, output)
    if code == 0:
        return Step("login scope", PASS, "session-scoped, no system-scoped twin, auto-login off")
    lines = [ln for ln in output.splitlines() if ln.strip()]
    tail = lines[-1][:160] if lines else ""
    # Its own 2 means "could not tell" and must not be promoted to a failure
    # here -- it fails closed for the same reason this script does.
    return Step("login scope", FAIL if code == 1 else UNKNOWN, tail)


def step_rebuild(head, previous_head):
    """Whether anything that only reaches the panel through an APK has changed.

    Measured against the last **successful** run of this script, recorded in
    STATE_FILE, because that is the only reference point the repo has: it cannot
    know what is installed on the phone. First run says so rather than claiming
    a verdict.
    """
    if not previous_head:
        return Step(
            "apk",
            UNKNOWN,
            "first run here -- rebuild if this pull touched web/ or android/ "
            "(make apk), then future runs will say",
        )
    # `head`, not the literal HEAD: the range has to be the one the report
    # above named, so a checkout that moved mid-run cannot make the two
    # disagree about which commit this verdict is about.
    code, output = git(["diff", "--name-only", f"{previous_head}..{head}"])
    if code != 0:
        return Step("apk", UNKNOWN, f"could not diff {previous_head}..{head} (history rewritten?)")
    changed = needs_rebuild(output.splitlines())
    if not changed:
        return Step("apk", PASS, f"nothing under web/ or android/ since {previous_head}")
    shown = ", ".join(changed[:3]) + (f" (+{len(changed) - 3} more)" if len(changed) > 3 else "")
    return Step(
        "apk",
        FAIL,
        f"{len(changed)} file(s) changed since {previous_head}: {shown} -- the phone needs "
        f"`make apk` and a reinstall, then `after_update.py --rebuilt` to clear this",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Post-update runbook: restart the login-scoped server and prove the new code is live."
    )
    parser.add_argument("--dry-run", action="store_true", help="report and plan, change nothing")
    parser.add_argument(
        "--self-test", action="store_true", dest="self_test", help="check the pure functions and exit"
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="seconds to wait for the socket either way"
    )
    parser.add_argument(
        "--rebuilt",
        action="store_true",
        help="record that the APK was rebuilt and reinstalled at this commit, and exit",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.rebuilt:
        # The way out of the `apk` finding. It reports FAIL, which makes the run
        # exit 1, which is what keeps the marker from advancing -- so without
        # this flag rebuilding and reinstalling could not clear it and the
        # script stayed red forever on the same commit. The docs claimed "only a
        # reinstall settles it", which was not true of the code. Found by review.
        #
        # An explicit acknowledgement rather than something inferred: the repo
        # cannot see what is installed on the phone, and a marker that advanced
        # on its own would quietly turn "you still have to reinstall" into
        # silence.
        code, head = git(["rev-parse", "--short", "HEAD"])
        if code != 0 or not head:
            print("not a git checkout -- nothing recorded", file=sys.stderr)
            return 2
        if not write_state({"head": head, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rebuilt": True}):
            print(f"could not write {STATE_FILE}", file=sys.stderr)
            return 2
        print(f"recorded: the APK on the phone is {head}. `apk` compares against it from now on.")
        return 0

    steps = []
    git_step, head = step_git_state()
    steps.append(git_step)

    platform = sys.platform
    python_exe = sys.executable
    config_path = None
    server_py = str(REPO_ROOT / "server" / "server.py")

    if platform == "win32":
        action, state = windows_task()
        if action is None:
            steps.append(Step("launcher", FAIL, state))
        else:
            parsed = parse_task_arguments(action.get("arguments", ""))
            if parsed is None:
                steps.append(
                    Step("launcher", UNKNOWN, "the task's arguments carry no quoted --config")
                )
            else:
                config_path, server_py = parsed["config"], parsed["server_py"]
                python_exe = python_for(action.get("execute", sys.executable))
                steps.append(Step("launcher", PASS, f"Scheduled Task '{TASK_NAME}', {state}"))
    elif platform.startswith("linux"):
        code, output = run(["systemctl", "--user", "is-enabled", UNIT_NAME], timeout=30)
        if code is None:
            steps.append(Step("launcher", UNKNOWN, output))
        elif code != 0:
            steps.append(
                Step("launcher", FAIL, f"{UNIT_NAME} is not enabled (run server/install_user_unit.sh)")
            )
        else:
            steps.append(Step("launcher", PASS, f"systemd user unit {UNIT_NAME}, {output.strip()}"))
            # The paths come out of the unit, exactly as the Windows branch
            # takes them out of the task action. Skipping this is what made the
            # whole Linux path dead code.
            unit = unit_file_path()
            try:
                parsed = parse_exec_start(unit.read_text(encoding="utf-8"))
            except OSError as exc:
                parsed = None
                steps.append(Step("unit file", UNKNOWN, f"could not read {unit}: {exc}"))
            if parsed is None:
                steps.append(
                    Step("unit file", UNKNOWN, f"no quoted --config in {unit}'s ExecStart")
                )
            else:
                config_path, server_py = parsed["config"], parsed["server_py"]
                python_exe = parsed["python"]
    elif platform == "darwin":
        # T3.10 is `blocked`, not done: the plist ships and has never run on a
        # Mac. Claiming a verdict here would be the one thing ADR 0010 asks this
        # repo not to do about macOS.
        steps.append(
            Step(
                "launcher",
                UNKNOWN,
                "macOS has no installer yet (T3.10, blocked -- no Mac). See docs/UPDATING.md",
            )
        )
    else:
        steps.append(Step("launcher", UNKNOWN, f"unsupported platform {platform}"))

    steps.extend(step_tests())

    if config_path:
        steps.append(step_config(python_exe, config_path, server_py))

    # The port comes from the repo's own loader rather than a second parser
    # here: `load_config` already dispatches on the suffix, and a port this
    # script guessed would probe a socket nobody is serving.
    port = None
    if config_path:
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from server.server import PORT, load_config

            port = int(load_config(config_path).get("port", PORT))
        except Exception as exc:
            steps.append(Step("port", UNKNOWN, f"could not read the port: {exc}"))
    if port is None and platform != "darwin":
        steps.append(Step("port", UNKNOWN, "no port to probe, so no restart was attempted"))

    # What gates the restart is what decides whether the server can come back
    # up: a launcher to ask, and a config it can parse. A red test suite does
    # **not** gate it, and that took a wrong turn to work out. The first cut
    # blocked on any failure, which reads as prudence and is not: the new code
    # is already on disk and the next login will load it whatever this script
    # does. The pull deployed it; the restart only decides whether the phone
    # waits until tomorrow to be told. Refusing here would leave the panel on
    # stale code *and* the tree broken, which is strictly worse than one of the
    # two. Test failures are reported and they still set the exit code.
    blockers = [s for s in steps if s.status == FAIL and s.name in ("launcher", "config")]
    if port is not None and not blockers:
        if platform == "win32":
            steps.append(restart_windows(port, args.timeout, args.dry_run))
        elif platform.startswith("linux"):
            steps.append(restart_linux(port, args.timeout, args.dry_run))
        if not args.dry_run:
            steps.append(step_payload(port))
            steps.append(step_login_scope(python_exe))
        else:
            # Without this a dry run printed "all clear" and exited 0 on the
            # exact machine state this script was written for -- a server
            # quietly serving last login's code. The one check that would have
            # noticed is the one a dry run cannot make. Found by review.
            steps.append(
                Step("payload", UNKNOWN, "not run in --dry-run, and it is the deciding check")
            )
    elif port is not None:
        steps.append(
            Step("restart", SKIP, f"{blockers[0].name} failed -- fix that, then run this again")
        )

    state = read_state()
    steps.append(step_rebuild(head, state.get("head")))

    print("\nafter_update:", REPO_ROOT)
    print(format_report(steps))

    code = overall_exit(steps)
    if code != 1 and not args.dry_run and head:
        # No **failure**, rather than a clean sweep, and the difference is a
        # deadlock the first real run walked into: a machine with no marker
        # reports `apk: unknown`, which makes the run exit 2, which -- when the
        # marker was only written on 0 -- meant the marker was never written and
        # every future run was a first run. The APK check could never start
        # working. A run that failed still keeps the old marker, because the
        # commit it was about was not seen through.
        write_state({"head": head, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})

    print(
        {
            0: "\nall clear.",
            1: "\nsomething is wrong above -- the panel may not be served the new code.",
            2: "\nnot everything could be determined; nothing above claims it is fine.",
        }[code]
    )
    return code


# --------------------------------------------------------------------------
# --self-test: the pure functions, on any box, with no launcher installed.
# --------------------------------------------------------------------------


UNIT_SAMPLE = (
    "[Service]\n"
    "Type=exec\n"
    'ExecStart="/usr/bin/python3" -u "/home/me/desk-panel/server/server.py"'
    ' --config "/home/me/desk-panel/server/config.toml"\n'
    "Restart=on-failure\n"
)


def self_test_cases():
    windows_args = (
        '"D:\\projetos-vscode\\desk-panel\\server\\server.py" '
        '--config "D:\\projetos-vscode\\desk-panel\\server\\config.json" '
        '--log-file "C:\\Users\\Someone\\AppData\\Local\\desk-panel\\server.log"'
    )
    spaces = (
        '"C:\\Program Files\\desk panel\\server\\server.py" '
        '--config "C:\\Program Files\\desk panel\\server\\config.toml"'
    )
    cases = [
        (
            "task arguments: the real shape",
            lambda: parse_task_arguments(windows_args)["config"].endswith("config.json"),
        ),
        (
            "task arguments: server.py is the first quoted run",
            lambda: parse_task_arguments(windows_args)["server_py"].endswith("server.py"),
        ),
        (
            "task arguments: the log file is read too",
            lambda: parse_task_arguments(windows_args)["log_file"].endswith("server.log"),
        ),
        (
            "task arguments: paths with spaces survive",
            lambda: parse_task_arguments(spaces)["config"]
            == "C:\\Program Files\\desk panel\\server\\config.toml",
        ),
        (
            "task arguments: a missing log file is not fatal",
            lambda: parse_task_arguments(spaces)["log_file"] is None,
        ),
        ("task arguments: no --config is None, not a guess", lambda: parse_task_arguments('"x.py"') is None),
        ("task arguments: empty is None", lambda: parse_task_arguments("") is None),
        ("task arguments: unquoted is None", lambda: parse_task_arguments("server.py --config c.toml") is None),
        (
            "ExecStart: the three quoted paths come back",
            lambda: parse_exec_start(UNIT_SAMPLE)["config"].endswith("config.toml"),
        ),
        (
            "ExecStart: server.py is the second quoted run, after the interpreter",
            lambda: parse_exec_start(UNIT_SAMPLE)["server_py"].endswith("server.py"),
        ),
        (
            "ExecStart: the interpreter is the first",
            lambda: parse_exec_start(UNIT_SAMPLE)["python"].endswith("python3"),
        ),
        (
            "ExecStart: a path with a space survives, which is why the file is read",
            lambda: parse_exec_start(
                'ExecStart="/usr/bin/python3" -u "/home/me/My Projects/dp/server/server.py"'
                ' --config "/home/me/My Projects/dp/server/config.toml"'
            )["config"]
            == "/home/me/My Projects/dp/server/config.toml",
        ),
        ("ExecStart: no ExecStart line is None", lambda: parse_exec_start("[Service]\nType=exec") is None),
        (
            "ExecStart: no --config is None, not a guess",
            lambda: parse_exec_start('ExecStart="/usr/bin/python3" -u "/x/server.py"') is None,
        ),
        ("ExecStart: empty is None", lambda: parse_exec_start("") is None),
        ("ExecStart: None is None", lambda: parse_exec_start(None) is None),
        (
            "python_for: pythonw.exe -> python.exe, same directory",
            lambda: python_for("C:\\Program Files\\Python313\\pythonw.exe")
            == "C:\\Program Files\\Python313\\python.exe",
        ),
        ("python_for: a plain python is left alone", lambda: python_for("/usr/bin/python3") == "/usr/bin/python3"),
        (
            "python_for: case does not matter on Windows",
            lambda: python_for("C:\\Py\\PYTHONW.EXE").endswith("python.exe"),
        ),
        ("rebuild: a theme change needs an APK", lambda: needs_rebuild(["web/themes/neon/theme.css"]) == ["web/themes/neon/theme.css"]),
        ("rebuild: an Activity change needs an APK", lambda: len(needs_rebuild(["android/app/src/main/java/X.java"])) == 1),
        ("rebuild: the server does not", lambda: needs_rebuild(["server/server.py"]) == []),
        ("rebuild: docs and tasks do not", lambda: needs_rebuild(["docs/UPDATING.md", "tasks/STATUS.md"]) == []),
        (
            "rebuild: mixed, only the two prefixes come back",
            lambda: needs_rebuild(["server/server.py", "web/js/app.js", "docs/x.md"]) == ["web/js/app.js"],
        ),
        ("rebuild: nothing changed", lambda: needs_rebuild([]) == []),
        ("exit: all pass is 0", lambda: overall_exit([Step("a", PASS), Step("b", SKIP)]) == 0),
        ("exit: one failure is 1", lambda: overall_exit([Step("a", PASS), Step("b", FAIL)]) == 1),
        ("exit: one unknown is 2", lambda: overall_exit([Step("a", PASS), Step("b", UNKNOWN)]) == 2),
        (
            "exit: failure outranks unknown",
            lambda: overall_exit([Step("a", UNKNOWN), Step("b", FAIL)]) == 1,
        ),
        ("exit: nothing ran is 0", lambda: overall_exit([]) == 0),
        ("report: one line per step", lambda: len(format_report([Step("a", PASS), Step("b", FAIL)]).splitlines()) == 2),
        ("report: the detail is carried", lambda: "because" in format_report([Step("a", FAIL, "because")])),
        (
            "expected keys: the moon is required when the provider is in the tree",
            lambda: "moon" in expected_weather_keys(True),
        ),
        (
            "expected keys: and is not when it is not",
            lambda: "moon" not in expected_weather_keys(False),
        ),
        (
            "expected keys: the chance of rain comes from the tree's own normalise",
            lambda: "precipProb" in expected_weather_keys(False),
        ),
    ]
    return cases


def self_test(stream=sys.stdout):
    sys.path.insert(0, str(REPO_ROOT))
    cases = self_test_cases()
    failures = 0
    for name, check in cases:
        try:
            ok = bool(check())
        except Exception as exc:  # a raising case is a failing case
            ok = False
            name = f"{name}  [{type(exc).__name__}: {exc}]"
        if not ok:
            failures += 1
            print(f"FAIL  {name}", file=stream)
    print(f"{len(cases) - failures}/{len(cases)} self-test cases passed", file=stream)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
