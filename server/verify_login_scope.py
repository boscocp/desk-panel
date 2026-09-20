#!/usr/bin/env python3
"""Assert that desk-panel's autostart on this machine is *session*-scoped.

Invariant 2 in the root CLAUDE.md: the server answering must mean a human is
logged in at the screen. That holds only while the launcher is the graphical
session of a specific user, and it is silently destroyed by anything of system
scope -- a Windows Service, a systemd system unit, a LaunchDaemon, `@reboot`,
a Docker container, or a systemd *user* unit reached from `default.target`.
See docs/adr/0010-login-signal-is-session-scoped.md; that ADR is the spec this
file checks, including the fields each OS's carrier must set.

    verify_login_scope.py              # check this machine, print a report
    verify_login_scope.py --self-test  # check the parsers against fixtures

Exit codes:

    0  every check passed
    1  at least one check failed -- the invariant is broken here
    2  at least one check could not be determined

2 is not "probably fine". A verifier that exits 0 when it could not look is
worse than no verifier, because the misconfiguration it exists to catch shows
up as "the panel is lit while nobody is logged in", which nobody reads as a
bug in the installer. So every check fails closed: a missing command, an
unreadable file or unexpected output all produce UNKNOWN, never PASS.

Structure, and why: every check is a **pure function over captured text**
(`parse_schtasks_xml`, `parse_systemctl_show`, `parse_launchctl_print`,
`parse_list_dependencies`, `parse_launchagent_plist`, `detect_autologin`,
`detect_system_scope`, `detect_wsl`, `detect_container`). Running commands and
reading files happens only in the thin `collect_*`/`run_*_checks` shell at the
bottom. That is what lets all three platforms be tested from fixtures on any
one machine -- there is no Mac here, and macOS still has to be checkable
(TT.10). It is the same rule server/CLAUDE.md applies to the request handler.

Standard library only, like the rest of server/.
"""
import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import namedtuple
from pathlib import Path

SERVICE_NAME = "desk-panel"
UNIT_NAME = "desk-panel.service"
AGENT_LABEL = "dev.bosco.deskpanel"
TASK_NAME = "desk-panel"

SCRIPT_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = SCRIPT_DIR / "fixtures" / "login_scope"

# Check outcomes. UNKNOWN is deliberately distinct from FAIL: one says the
# machine is wrong, the other says this tool could not tell. Both are non-zero.
PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"

Check = namedtuple("Check", "name status detail")

# How a piece of text was obtained. The pure functions need this to tell
# "the file says auto-login is off" from "there is no such file" from "the
# file is there and I could not read it" -- three different answers that a
# bare string cannot carry.
CAPTURED = "captured"   # we have the real output
MISSING = "missing"     # the command or file does not exist on this machine
ERROR = "error"         # it exists and we could not read it

Capture = namedtuple("Capture", "status text")


def captured(text):
    return Capture(CAPTURED, text)


def missing(why=""):
    return Capture(MISSING, why)


def unreadable(why=""):
    return Capture(ERROR, why)


class ParseError(Exception):
    """Captured text that is not the shape this parser knows.

    Never folded into "the thing is absent" -- absence is an answer, and
    unparsable output is not.
    """


# --------------------------------------------------------------------------
# Windows: Scheduled Task
# --------------------------------------------------------------------------

_TASK_NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"


def _strip_namespaces(root):
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.startswith("{"):
            element.tag = element.tag.split("}", 1)[1]
    return root


def _text(root, path):
    found = root.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _xml_bool(value):
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def parse_schtasks_xml(text):
    """Pure: parse `schtasks /query /tn desk-panel /xml ONE` output.

    Returns {"found": False, ...} for the ERROR line schtasks prints when the
    task does not exist, and a dict of the ADR 0010 fields otherwise. Raises
    ParseError for anything else.
    """
    stripped = text.lstrip("﻿ \t\r\n")
    if not stripped:
        raise ParseError("empty schtasks output")
    if not stripped.startswith("<"):
        if "ERROR:" in stripped:
            return {"found": False, "message": stripped.splitlines()[0].strip()}
        raise ParseError(f"schtasks output is neither XML nor an ERROR line: {stripped[:80]!r}")

    try:
        # Parsed from `str`, not bytes, on purpose: schtasks declares
        # encoding="UTF-16" and expat rejects that declaration on a byte
        # string it is handed as UTF-8. Decoding is the shell's job.
        root = _strip_namespaces(ET.fromstring(stripped))
    except ET.ParseError as exc:
        raise ParseError(f"schtasks XML is malformed: {exc}") from None

    triggers_element = root.find("Triggers")
    triggers = [] if triggers_element is None else [child.tag for child in triggers_element]

    return {
        "found": True,
        "triggers": triggers,
        "user_id": _text(root, "Principals/Principal/UserId"),
        "logon_type": _text(root, "Principals/Principal/LogonType"),
        "run_level": _text(root, "Principals/Principal/RunLevel"),
        "execution_time_limit": _text(root, "Settings/ExecutionTimeLimit"),
        "disallow_start_if_on_batteries": _xml_bool(
            _text(root, "Settings/DisallowStartIfOnBatteries")
        ),
        "stop_if_going_on_batteries": _xml_bool(
            _text(root, "Settings/StopIfGoingOnBatteries")
        ),
        "enabled": _xml_bool(_text(root, "Settings/Enabled")),
        "command": _text(root, "Actions/Exec/Command"),
    }


def check_windows_task(task):
    """Pure: the ADR 0010 Windows row, field by field."""
    if not task.get("found"):
        return [Check(
            "windows.task.exists", FAIL,
            f"no Scheduled Task named {TASK_NAME!r}: {task.get('message', '')}",
        )]

    checks = [Check("windows.task.exists", PASS, f"task {TASK_NAME!r} is registered")]

    triggers = task.get("triggers") or []
    if triggers == ["LogonTrigger"]:
        checks.append(Check("windows.task.logon-trigger", PASS, "one LogonTrigger"))
    else:
        checks.append(Check(
            "windows.task.logon-trigger", FAIL,
            f"triggers are {triggers or ['(none)']}; the only allowed trigger is LogonTrigger "
            f"-- a BootTrigger or a schedule fires without a login",
        ))

    logon_type = task.get("logon_type")
    checks.append(Check(
        "windows.task.logon-type",
        PASS if logon_type == "InteractiveToken" else FAIL,
        f"LogonType={logon_type!r}, must be 'InteractiveToken' so the task runs in the session",
    ))

    # Absent means the Task Scheduler default of 72 hours, which kills the
    # server on day four of an uptime streak while the user is still logged in.
    limit = task.get("execution_time_limit")
    checks.append(Check(
        "windows.task.execution-time-limit",
        PASS if limit == "PT0S" else FAIL,
        f"ExecutionTimeLimit={limit or '(absent, defaults to PT72H)'}, must be 'PT0S'",
    ))

    # Absent also defaults to true here, so None is a failure, not an unknown.
    batteries = task.get("disallow_start_if_on_batteries")
    checks.append(Check(
        "windows.task.batteries",
        PASS if batteries is False else FAIL,
        f"DisallowStartIfOnBatteries={'(absent, defaults to true)' if batteries is None else batteries}"
        f", must be false",
    ))

    # Same shape as the one above, and the same default: absent means true,
    # which stops the server the moment a laptop leaves the mains. The panel
    # reads that as a logout and sleeps while its owner is still sitting there.
    stop_on_battery = task.get("stop_if_going_on_batteries")
    checks.append(Check(
        "windows.task.stop-on-battery",
        PASS if stop_on_battery is False else FAIL,
        f"StopIfGoingOnBatteries="
        f"{'(absent, defaults to true)' if stop_on_battery is None else stop_on_battery}"
        f", must be false",
    ))

    # Absent is an answer here, not an inability to tell, and it is the
    # opposite of the two settings above: the Task Scheduler omits this element
    # at its default, and the default is enabled. A task that really is
    # disabled writes <Enabled>false</Enabled> -- checked against a live task
    # on Windows 11, disabled and re-enabled, where the element appeared and
    # vanished accordingly. Reporting absent as UNKNOWN made every correctly
    # enabled task come back as exit 2.
    enabled = task.get("enabled")
    checks.append(Check(
        "windows.task.enabled",
        FAIL if enabled is False else PASS,
        "Settings/Enabled=(absent, which the Task Scheduler writes for enabled)"
        if enabled is None else f"Settings/Enabled={enabled}",
    ))
    return checks


# --------------------------------------------------------------------------
# Linux: systemd user unit
# --------------------------------------------------------------------------

def parse_systemctl_show(text):
    """Pure: `systemctl [--user] show UNIT` output into a KEY -> VALUE dict.

    Values are taken verbatim after the first '=' -- several of them (ExecStart)
    contain further '=' signs.
    """
    properties = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key:
            continue
        properties[key] = value
    if not properties:
        raise ParseError("no KEY=VALUE lines in systemctl show output")
    return properties


def _unit_list(properties, key):
    return properties.get(key, "").split()


def check_systemd_user_unit(properties):
    """Pure: the ADR 0010 Linux row against `systemctl --user show` output."""
    load_state = properties.get("LoadState")
    if load_state != "loaded":
        return [Check(
            "linux.unit.loaded", FAIL,
            f"LoadState={load_state!r} for {UNIT_NAME}: "
            f"{properties.get('LoadError', 'the unit is not installed')}",
        )]

    checks = [Check("linux.unit.loaded", PASS, f"{UNIT_NAME} is loaded")]

    unit_type = properties.get("Type")
    checks.append(Check(
        "linux.unit.type",
        PASS if unit_type == "exec" else FAIL,
        f"Type={unit_type!r}, must be 'exec'",
    ))

    # WantedBy starts the unit with the graphical session...
    wanted_by = _unit_list(properties, "WantedBy")
    checks.append(Check(
        "linux.unit.wanted-by",
        PASS if "graphical-session.target" in wanted_by else FAIL,
        f"WantedBy={wanted_by or ['(nothing -- unit not enabled)']}, "
        f"must include graphical-session.target",
    ))

    # ...and PartOf is what makes logging out stop it. Without it the unit
    # survives logout, because logind defaults to KillUserProcesses=no.
    part_of = _unit_list(properties, "PartOf")
    checks.append(Check(
        "linux.unit.part-of",
        PASS if "graphical-session.target" in part_of else FAIL,
        f"PartOf={part_of or ['(nothing)']}, must include graphical-session.target "
        f"or the server outlives the session that started it",
    ))

    file_state = properties.get("UnitFileState")
    if file_state is None:
        checks.append(Check("linux.unit.enabled", UNKNOWN, "UnitFileState not reported"))
    else:
        checks.append(Check(
            "linux.unit.enabled",
            PASS if file_state in ("enabled", "enabled-runtime") else FAIL,
            f"UnitFileState={file_state!r}",
        ))
    return checks


_UNIT_NAME_RE = re.compile(
    r"[A-Za-z0-9@:_.\\-]+\."
    r"(?:service|socket|target|timer|path|mount|automount|swap|slice|scope|device)\b"
)


def parse_list_dependencies(text):
    """Pure: unit names out of `systemctl list-dependencies` tree output.

    The tree is drawn with box glyphs and a status bullet per line; the regex
    skips both. Escaped names (app-foo\\x2dbar@autostart.service) survive.
    """
    return {match.group(0) for line in text.splitlines()
            for match in [_UNIT_NAME_RE.search(line)] if match}


def check_not_in_default_closure(dependencies):
    """Pure: ADR 0010's stronger property, proved directly.

    `default.target` is reached by the user manager at boot when lingering is
    on, and by an SSH session even when it is off. A unit anywhere in that
    closure answers with nobody at the screen.
    """
    if UNIT_NAME in dependencies:
        return Check(
            "linux.unit.not-in-default-closure", FAIL,
            f"{UNIT_NAME} is pulled in by default.target, which is reached at boot with "
            f"lingering on and by any SSH session -- it would answer at the greeter",
        )
    return Check(
        "linux.unit.not-in-default-closure", PASS,
        f"{UNIT_NAME} is not in the transitive closure of default.target "
        f"({len(dependencies)} units scanned)",
    )


# --------------------------------------------------------------------------
# macOS: LaunchAgent
# --------------------------------------------------------------------------

def parse_launchctl_print(text):
    """Pure: `launchctl print gui/<uid>/<label>` output.

    Only the handful of lines that matter is extracted. Lines from the nested
    `environment = { KEY => VALUE }` blocks partition on '=' too, but their
    keys never collide with the ones read here.
    """
    stripped = text.strip()
    if not stripped:
        raise ParseError("empty launchctl print output")
    if "Could not find service" in stripped:
        return {"found": False, "message": stripped.splitlines()[0].strip()}
    if stripped.startswith("Bad request") or stripped.startswith("Unrecognized"):
        raise ParseError(f"launchctl rejected the request: {stripped.splitlines()[0]}")

    result = {"found": True, "properties": set()}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if key == "type":
            result["type"] = value
        elif key == "path":
            result["path"] = value
        elif key == "state":
            result["state"] = value
        elif key == "program":
            result["program"] = value
        elif key == "domain":
            # "gui/501 [100005]" -- the bracketed handle is noise.
            result["domain"] = value.split()[0] if value else ""
        elif key == "properties":
            result["properties"] = {item.strip() for item in value.split("|") if item.strip()}
    if "type" not in result:
        raise ParseError("launchctl print output has no 'type =' line")
    return result


def parse_launchagent_plist(text):
    """Pure: a LaunchAgent plist into a dict.

    `LimitLoadToSessionType` lives here and not in `launchctl print`, which is
    why the plist has to be read as well as the runtime state.
    """
    try:
        return plistlib.loads(text.encode("utf-8"))
    except Exception as exc:  # plistlib raises several unrelated types
        raise ParseError(f"not a readable plist: {exc}") from None


def _session_types(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def check_macos_agent(plist, printed, plist_path):
    """Pure: the ADR 0010 macOS row."""
    if plist is None:
        return [Check(
            "macos.agent.exists", FAIL,
            f"no LaunchAgent plist for {AGENT_LABEL} in ~/Library/LaunchAgents",
        )]

    checks = [Check("macos.agent.exists", PASS, f"{plist_path}")]

    # str() of a Path renders with the *host's* separator, so on Windows a
    # perfectly good ~/Library/LaunchAgents path arrives with backslashes and
    # this POSIX-shaped test fails. Normalising keeps TT.10's promise -- all
    # three platforms' checks are exercised on any one machine -- true on the
    # primary platform too.
    path = str(plist_path).replace("\\", "/")
    in_user_agents = "/Library/LaunchAgents/" in path and not path.startswith("/Library/")
    checks.append(Check(
        "macos.agent.location",
        PASS if in_user_agents else FAIL,
        f"{path} -- must live in ~/Library/LaunchAgents, never /Library/LaunchAgents "
        f"(loads for every user) or /Library/LaunchDaemons (loads with no user)",
    ))

    session_types = _session_types(plist.get("LimitLoadToSessionType"))
    checks.append(Check(
        "macos.agent.session-type",
        PASS if session_types == ["Aqua"] else FAIL,
        f"LimitLoadToSessionType={session_types or '(unset)'}, must be exactly 'Aqua'; "
        f"unset also loads in LoginWindow and Background, i.e. at the login screen",
    ))

    checks.append(Check(
        "macos.agent.run-at-load",
        PASS if plist.get("RunAtLoad") is True else FAIL,
        f"RunAtLoad={plist.get('RunAtLoad')!r}, must be true",
    ))

    if printed is None:
        checks.append(Check("macos.agent.loaded", UNKNOWN, "launchctl print was not captured"))
    elif not printed.get("found"):
        checks.append(Check(
            "macos.agent.loaded", FAIL,
            f"{AGENT_LABEL} is not loaded in the gui domain: {printed.get('message', '')}",
        ))
    else:
        domain = printed.get("domain", "")
        kind = printed.get("type")
        ok = kind == "LaunchAgent" and domain.startswith("gui/")
        checks.append(Check(
            "macos.agent.loaded",
            PASS if ok else FAIL,
            f"loaded as type={kind!r} in domain={domain!r}; must be a LaunchAgent in gui/<uid>",
        ))
    return checks


# --------------------------------------------------------------------------
# Cross-platform detectors, all pure
# --------------------------------------------------------------------------

def _ini_sections(text):
    """Pure: a minimal INI reader. configparser raises on the duplicate keys
    and stray lines that real display-manager drop-ins contain, and a raised
    exception here would read as "cannot determine" for a file we can see."""
    sections = {}
    current = sections.setdefault("", {})
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1].strip().lower(), {})
            continue
        key, separator, value = line.partition("=")
        if separator:
            current[key.strip().lower()] = value.strip()
    return sections


def _gdm_autologin(text):
    daemon = _ini_sections(text).get("daemon", {})
    if daemon.get("automaticloginenable", "").lower() in ("true", "1", "yes"):
        return daemon.get("automaticlogin") or "(unnamed user)"
    return None


def _sddm_autologin(text):
    user = _ini_sections(text).get("autologin", {}).get("user", "")
    return user or None


def _lightdm_autologin(text):
    for name, section in _ini_sections(text).items():
        if name.startswith("seat"):
            user = section.get("autologin-user", "")
            if user:
                return user
    return None


_LINUX_DISPLAY_MANAGERS = (
    ("gdm", _gdm_autologin),
    ("sddm", _sddm_autologin),
    ("lightdm", _lightdm_autologin),
)


def detect_autologin(platform, sources):
    """Pure: is the graphical session started without a human typing a password?

    ADR 0010: auto-login defeats the invariant on every OS and no launcher can
    fix it -- the session starts with nobody present and the signal degrades to
    "the machine is powered on". It is detected and reported, not solved.

    `sources` maps a source name to a Capture. Returns one Check.
    """
    if platform == "win32":
        return _autologin_windows(sources)
    if platform == "darwin":
        return _autologin_darwin(sources)
    return _autologin_linux(sources)


def _autologin_windows(sources):
    capture = sources.get("winlogon")
    if capture is None:
        return Check("autologin", UNKNOWN, "could not read the Winlogon key: not collected")
    # MISSING is an answer, not an inability to look: the value genuinely is
    # not there, which is exactly what "no auto-login" looks like in the
    # registry. Only ERROR means we could not tell.
    if capture.status == MISSING:
        return Check("autologin", PASS, f"AutoAdminLogon is not set ({capture.text})")
    if capture.status != CAPTURED:
        return Check("autologin", UNKNOWN,
                     f"could not read the Winlogon key: {capture.text}")
    if "ERROR:" in capture.text:
        return Check("autologin", PASS, "AutoAdminLogon is not set")
    match = re.search(r"AutoAdminLogon\s+REG_[A-Z_]+\s+(\S+)", capture.text)
    if match is None:
        return Check("autologin", UNKNOWN,
                     "reg query returned no AutoAdminLogon value and no error")
    value = match.group(1).strip()
    if value == "0":
        return Check("autologin", PASS, "AutoAdminLogon=0")
    return Check("autologin", FAIL,
                 f"AutoAdminLogon={value} -- Windows logs in without a human")


def _autologin_darwin(sources):
    capture = sources.get("loginwindow")
    if capture is None or capture.status != CAPTURED:
        return Check("autologin", UNKNOWN,
                     f"could not read com.apple.loginwindow: "
                     f"{capture.text if capture else 'not collected'}")
    text = capture.text.strip()
    if "does not exist" in text:
        return Check("autologin", PASS, "autoLoginUser is not set")
    if not text:
        return Check("autologin", UNKNOWN, "defaults read returned nothing")
    return Check("autologin", FAIL,
                 f"autoLoginUser={text.splitlines()[0]!r} -- macOS logs in without a human")


def _autologin_linux(sources):
    evidence = []
    looked_at = []
    for name, parse in _LINUX_DISPLAY_MANAGERS:
        capture = sources.get(name)
        if capture is None or capture.status == MISSING:
            continue  # that display manager is not installed here
        if capture.status == ERROR:
            return Check("autologin", UNKNOWN,
                         f"cannot read the {name} configuration: {capture.text}")
        looked_at.append(name)
        user = parse(capture.text)
        if user:
            evidence.append(f"{name} auto-logs in {user!r}")
    if not looked_at:
        return Check("autologin", UNKNOWN,
                     "no gdm, sddm or lightdm configuration found; cannot tell whether "
                     "the session starts without a human")
    if evidence:
        return Check("autologin", FAIL, "; ".join(evidence))
    return Check("autologin", PASS, f"no automatic login configured ({', '.join(looked_at)})")


def detect_system_scope(platform, sources):
    """Pure: does a system-scoped equivalent exist alongside the session one?

    The forbidden class from ADR 0010: a Windows Service, a systemd system
    unit, a LaunchDaemon, an `@reboot` crontab entry, a Docker container. Each
    answers with nobody logged in, so one of them running makes the panel lie
    however correct the session-scoped entry is.
    """
    if platform == "win32":
        return _system_scope_windows(sources)
    if platform == "darwin":
        return _system_scope_darwin(sources)
    return _system_scope_linux(sources)


def _system_scope_windows(sources):
    capture = sources.get("sc_query")
    if capture is None or capture.status != CAPTURED:
        return Check("no-system-scope", UNKNOWN,
                     f"could not query the service control manager: "
                     f"{capture.text if capture else 'not collected'}")
    text = capture.text
    if "SERVICE_NAME:" in text:
        return Check("no-system-scope", FAIL,
                     f"a Windows Service named {SERVICE_NAME!r} exists -- it answers "
                     f"before anyone logs in and at the lock screen")
    if "1060" in text or "does not exist" in text:
        return Check("no-system-scope", PASS, f"no Windows Service named {SERVICE_NAME!r}")
    return Check("no-system-scope", UNKNOWN,
                 f"unrecognised sc.exe output: {text.strip().splitlines()[:1]}")


def _system_scope_linux(sources):
    findings = []

    capture = sources.get("systemd_system")
    if capture is None or capture.status != CAPTURED:
        return Check("no-system-scope", UNKNOWN,
                     f"could not query the system systemd manager: "
                     f"{capture.text if capture else 'not collected'}")
    try:
        properties = parse_systemctl_show(capture.text)
    except ParseError as exc:
        return Check("no-system-scope", UNKNOWN, f"systemctl show: {exc}")
    load_state = properties.get("LoadState")
    if load_state is None:
        return Check("no-system-scope", UNKNOWN, "systemctl show reported no LoadState")
    if load_state != "not-found":
        findings.append(f"a systemd *system* unit {UNIT_NAME} exists (LoadState={load_state})")

    capture = sources.get("crontab")
    if capture is not None and capture.status == ERROR:
        return Check("no-system-scope", UNKNOWN, f"cannot read the crontab: {capture.text}")
    if capture is not None and capture.status == CAPTURED:
        for line in capture.text.splitlines():
            if line.strip().startswith("@reboot") and (
                SERVICE_NAME in line or "server.py" in line
            ):
                findings.append(f"an @reboot crontab entry starts the server: {line.strip()}")

    capture = sources.get("docker_ps")
    if capture is not None and capture.status == ERROR:
        return Check("no-system-scope", UNKNOWN, f"cannot list containers: {capture.text}")
    if capture is not None and capture.status == CAPTURED:
        for line in capture.text.splitlines()[1:]:
            if SERVICE_NAME in line:
                findings.append(f"a container is running the server: {line.strip()}")

    if findings:
        return Check("no-system-scope", FAIL, "; ".join(findings))
    return Check("no-system-scope", PASS,
                 "no systemd system unit, no @reboot entry, no container running the server")


def _system_scope_darwin(sources):
    findings = []

    capture = sources.get("launchdaemon_files")
    if capture is None or capture.status == ERROR:
        return Check("no-system-scope", UNKNOWN,
                     f"could not list /Library/LaunchDaemons: "
                     f"{capture.text if capture else 'not collected'}")
    if capture.status == CAPTURED:
        for line in capture.text.splitlines():
            if line.strip():
                findings.append(f"a LaunchDaemon exists: {line.strip()}")

    capture = sources.get("launchctl_system")
    if capture is not None and capture.status == ERROR:
        return Check("no-system-scope", UNKNOWN,
                     f"could not query the system launchd domain: {capture.text}")
    if capture is not None and capture.status == CAPTURED:
        try:
            printed = parse_launchctl_print(capture.text)
        except ParseError as exc:
            return Check("no-system-scope", UNKNOWN, f"launchctl print system: {exc}")
        if printed.get("found"):
            findings.append(f"{AGENT_LABEL} is loaded in the system domain")

    if findings:
        return Check("no-system-scope", FAIL, "; ".join(findings))
    return Check("no-system-scope", PASS, "no LaunchDaemon and nothing in the system domain")


def detect_wsl(platform, sources):
    """Pure: is this a WSL distribution?

    WSL's session has no relationship to whether anyone is logged in at the
    Windows desktop -- it survives lock and outlives logout -- so the server
    running there reports the wrong thing even with a perfect systemd unit.
    """
    if platform != "linux":
        return Check("not-wsl", PASS, f"platform is {platform}, WSL does not apply")

    env_capture = sources.get("env")
    env_markers = env_capture.text.strip() if env_capture and env_capture.status == CAPTURED else ""
    if env_markers:
        return Check("not-wsl", FAIL, f"WSL environment variables are set: {env_markers}")

    capture = sources.get("osrelease")
    if capture is None or capture.status != CAPTURED:
        return Check("not-wsl", UNKNOWN,
                     f"could not read /proc/sys/kernel/osrelease: "
                     f"{capture.text if capture else 'not collected'}")
    release = capture.text.strip()
    lowered = release.lower()
    if "microsoft" in lowered or "wsl" in lowered:
        return Check("not-wsl", FAIL, f"kernel release {release!r} is WSL")
    return Check("not-wsl", PASS, f"kernel release {release!r}")


_CONTAINER_CGROUP_MARKERS = ("/docker/", "/docker-", "/lxc/", "kubepods", "/libpod-", "/podman")


def detect_container(platform, sources):
    """Pure: are we inside a container?

    A container answers with nobody logged in at all, which is the most
    complete way to break the invariant. ADR 0003 normalises `docker compose`
    for the Android toolchain, so the wrong reflex is close at hand.
    """
    env_capture = sources.get("env_container")
    env_marker = env_capture.text.strip() if env_capture and env_capture.status == CAPTURED else ""
    if env_marker:
        return Check("not-container", FAIL, f"$container is set to {env_marker!r}")

    if platform != "linux":
        return Check("not-container", PASS,
                     f"platform is {platform} and $container is unset")

    capture = sources.get("detect_virt")
    if capture is not None and capture.status == CAPTURED:
        verdict = capture.text.strip()
        if verdict and verdict != "none":
            return Check("not-container", FAIL, f"systemd-detect-virt reports {verdict!r}")

    markers = []
    for name in ("dockerenv", "containerenv"):
        marker = sources.get(name)
        if marker is not None and marker.status == CAPTURED:
            markers.append(name)
        elif marker is not None and marker.status == ERROR:
            return Check("not-container", UNKNOWN, f"cannot stat {name}: {marker.text}")

    cgroup = sources.get("cgroup")
    if cgroup is not None and cgroup.status == ERROR:
        return Check("not-container", UNKNOWN, f"cannot read the cgroup: {cgroup.text}")
    if cgroup is not None and cgroup.status == CAPTURED:
        lowered = cgroup.text.lower()
        if any(needle in lowered for needle in _CONTAINER_CGROUP_MARKERS):
            markers.append("cgroup")

    if markers:
        return Check("not-container", FAIL, f"container markers present: {', '.join(markers)}")

    if capture is not None and capture.status == CAPTURED and capture.text.strip() == "none":
        return Check("not-container", PASS, "systemd-detect-virt reports none")

    # Under cgroup v2 a container's /proc/self/cgroup reads "0::/", exactly
    # like the host -- verified against `docker run alpine`. So with no
    # detect-virt to ask, the absence of markers proves nothing.
    return Check("not-container", UNKNOWN,
                 "systemd-detect-virt is unavailable and cgroup v2 cannot distinguish a "
                 "container from the host; cannot tell")


# --------------------------------------------------------------------------
# The shell: everything that touches the machine lives below this line
# --------------------------------------------------------------------------

def _decode(data):
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def run_command(command, timeout=15):
    """Capture a command's combined output. Never raises."""
    executable = shutil.which(command[0])
    if executable is None:
        return missing(f"{command[0]} is not installed")
    try:
        completed = subprocess.run(
            [executable] + list(command[1:]),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return unreadable(f"{command[0]} failed: {exc}")
    return captured(_decode(completed.stdout))


_WINLOGON_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"


def read_registry_autologin():
    """Capture HKLM's AutoAdminLogon. Never raises. Windows only.

    Not `reg query`: reg.exe localises its failure line, so on a pt-BR Windows
    it prints "ERRO:" where the parser looked for "ERROR:" and a value that is
    simply not set came back as "could not look" -- UNKNOWN, exit 2, on a
    machine with nothing wrong with it. winreg raises instead of printing, and
    the exception type is the same in every language.

    The hit is rendered in reg.exe's shape so the committed fixtures stay the
    contract for the pure function.
    """
    try:
        import winreg
    except ImportError:
        return missing("winreg is unavailable off Windows")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _WINLOGON_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "AutoAdminLogon")
    except FileNotFoundError:
        return missing(r"no AutoAdminLogon value under HKLM\...\Winlogon")
    except OSError as exc:
        return unreadable(f"cannot read AutoAdminLogon: {exc}")
    return captured(f"    AutoAdminLogon    REG_SZ    {value}")


def read_file(path):
    """Capture a file's text. Never raises."""
    candidate = Path(path)
    try:
        if not candidate.exists():
            return missing(f"{path} does not exist")
        return captured(candidate.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return unreadable(f"cannot read {path}: {exc}")


def file_present(path):
    """A Capture whose status alone answers "is this marker file there?"."""
    candidate = Path(path)
    try:
        return captured(path) if candidate.exists() else missing(f"{path} does not exist")
    except OSError as exc:
        return unreadable(f"cannot stat {path}: {exc}")


def _environment_sources(environ):
    wsl_markers = " ".join(
        f"{name}={environ[name]}" for name in ("WSL_DISTRO_NAME", "WSL_INTEROP")
        if environ.get(name)
    )
    return {
        "wsl_env": captured(wsl_markers),
        "container_env": captured(environ.get("container", "")),
    }


def run_linux_checks(environ=None):
    environ = os.environ if environ is None else environ
    checks = []

    show = run_command(["systemctl", "--user", "show", UNIT_NAME])
    if show.status != CAPTURED:
        checks.append(Check("linux.unit", UNKNOWN,
                            f"cannot query the user systemd manager: {show.text}"))
    else:
        try:
            checks.extend(check_systemd_user_unit(parse_systemctl_show(show.text)))
        except ParseError as exc:
            checks.append(Check("linux.unit", UNKNOWN, str(exc)))

    dependencies = run_command(["systemctl", "--user", "list-dependencies", "default.target"])
    if dependencies.status != CAPTURED:
        checks.append(Check("linux.unit.not-in-default-closure", UNKNOWN,
                            f"cannot list default.target dependencies: {dependencies.text}"))
    else:
        checks.append(check_not_in_default_closure(parse_list_dependencies(dependencies.text)))

    checks.append(detect_system_scope("linux", {
        "systemd_system": run_command(["systemctl", "show", UNIT_NAME]),
        "crontab": run_command(["crontab", "-l"]),
        "docker_ps": run_command(["docker", "ps", "--format", "{{.Names}} {{.Image}}"]),
    }))
    checks.append(detect_autologin("linux", {
        "gdm": _first_readable(["/etc/gdm/custom.conf", "/etc/gdm3/custom.conf",
                                "/etc/gdm3/daemon.conf"]),
        "sddm": _merged_sddm(),
        "lightdm": _first_readable(["/etc/lightdm/lightdm.conf"]),
    }))
    environment = _environment_sources(environ)
    checks.append(detect_wsl("linux", {
        "osrelease": read_file("/proc/sys/kernel/osrelease"),
        "env": environment["wsl_env"],
    }))
    checks.append(detect_container("linux", {
        "detect_virt": run_command(["systemd-detect-virt", "--container"]),
        "dockerenv": file_present("/.dockerenv"),
        "containerenv": file_present("/run/.containerenv"),
        "cgroup": read_file("/proc/self/cgroup"),
        "env_container": environment["container_env"],
    }))
    return checks


def _first_readable(paths):
    last = missing(f"none of {paths} exists")
    for path in paths:
        capture = read_file(path)
        if capture.status != MISSING:
            return capture
        last = capture
    return last


def _merged_sddm():
    """sddm reads /etc/sddm.conf plus every drop-in; a drop-in can switch
    auto-login on with the base file saying nothing."""
    parts = []
    saw_one = False
    for path in [Path("/etc/sddm.conf")] + sorted(Path("/etc/sddm.conf.d").glob("*.conf")
                                                  if Path("/etc/sddm.conf.d").is_dir() else []):
        capture = read_file(path)
        if capture.status == ERROR:
            return capture
        if capture.status == CAPTURED:
            saw_one = True
            parts.append(capture.text)
    if not saw_one:
        return missing("no /etc/sddm.conf and no drop-ins")
    return captured("\n".join(parts))


def run_windows_checks(environ=None):
    environ = os.environ if environ is None else environ
    checks = []

    export = run_command(["schtasks", "/query", "/tn", TASK_NAME, "/xml", "ONE"])
    if export.status != CAPTURED:
        checks.append(Check("windows.task", UNKNOWN,
                            f"cannot query the task scheduler: {export.text}"))
    else:
        try:
            checks.extend(check_windows_task(parse_schtasks_xml(export.text)))
        except ParseError as exc:
            checks.append(Check("windows.task", UNKNOWN, str(exc)))

    checks.append(detect_system_scope("win32", {
        "sc_query": run_command(["sc", "query", SERVICE_NAME]),
    }))
    checks.append(detect_autologin("win32", {"winlogon": read_registry_autologin()}))
    checks.append(detect_wsl("win32", {}))
    checks.append(detect_container("win32", {
        "env_container": _environment_sources(environ)["container_env"],
    }))
    return checks


def run_macos_checks(environ=None):
    environ = os.environ if environ is None else environ
    checks = []

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
    plist_capture = read_file(plist_path)
    printed = None
    print_capture = run_command(["launchctl", "print", f"gui/{os.getuid()}/{AGENT_LABEL}"])
    if print_capture.status == CAPTURED:
        try:
            printed = parse_launchctl_print(print_capture.text)
        except ParseError as exc:
            checks.append(Check("macos.agent.loaded", UNKNOWN, str(exc)))

    if plist_capture.status == MISSING:
        checks.extend(check_macos_agent(None, printed, plist_path))
    elif plist_capture.status == ERROR:
        checks.append(Check("macos.agent.exists", UNKNOWN, plist_capture.text))
    else:
        try:
            checks.extend(check_macos_agent(
                parse_launchagent_plist(plist_capture.text), printed, plist_path))
        except ParseError as exc:
            checks.append(Check("macos.agent.exists", UNKNOWN, str(exc)))

    daemons = Path("/Library/LaunchDaemons")
    try:
        listing = "\n".join(str(path) for path in daemons.glob(f"*{AGENT_LABEL}*")) \
            if daemons.is_dir() else ""
        daemon_capture = captured(listing)
    except OSError as exc:
        daemon_capture = unreadable(str(exc))
    checks.append(detect_system_scope("darwin", {
        "launchdaemon_files": daemon_capture,
        "launchctl_system": run_command(["launchctl", "print", f"system/{AGENT_LABEL}"]),
    }))
    checks.append(detect_autologin("darwin", {
        "loginwindow": run_command([
            "defaults", "read", "/Library/Preferences/com.apple.loginwindow", "autoLoginUser",
        ]),
    }))
    checks.append(detect_wsl("darwin", {}))
    checks.append(detect_container("darwin", {
        "env_container": _environment_sources(environ)["container_env"],
    }))
    return checks


def run_checks(platform=None, environ=None):
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return run_windows_checks(environ)
    if platform == "darwin":
        return run_macos_checks(environ)
    if platform.startswith("linux"):
        return run_linux_checks(environ)
    return [Check("platform", UNKNOWN,
                  f"{platform} is not one of the three platforms ADR 0010 covers")]


def exit_code(checks):
    """1 beats 2 beats 0: a definite failure is the most useful thing to
    report, and "could not tell" must never come out as success."""
    if not checks:
        return 2
    if any(check.status == FAIL for check in checks):
        return 1
    if any(check.status == UNKNOWN for check in checks):
        return 2
    return 0


def format_report(checks):
    labels = {PASS: "PASS", FAIL: "FAIL", UNKNOWN: "????"}
    lines = [f"[{labels[check.status]}] {check.name}: {check.detail}" for check in checks]
    failed = sum(1 for check in checks if check.status == FAIL)
    unknown = sum(1 for check in checks if check.status == UNKNOWN)
    if failed:
        lines.append(f"\n{failed} check(s) failed: the server here can answer with nobody "
                     f"logged in. See docs/adr/0010-login-signal-is-session-scoped.md.")
    elif unknown:
        lines.append(f"\n{unknown} check(s) could not be determined. This is not a pass: "
                     f"the verifier could not look, so nothing is proved.")
    else:
        lines.append("\nLogin scope verified: the server answers only inside a graphical "
                     "session of this user.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# --self-test: the parsers against the bundled fixtures
# --------------------------------------------------------------------------

def fixture(name):
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def statuses(checks):
    return {check.name: check.status for check in checks}


def self_test_cases():
    """(label, actual, expected) triples. Pure -- no command runs here."""
    cases = []

    # -- Windows ----------------------------------------------------------
    good = parse_schtasks_xml(fixture("windows_schtasks_good.xml"))
    cases.append(("schtasks good: triggers", good["triggers"], ["LogonTrigger"]))
    cases.append(("schtasks good: logon type", good["logon_type"], "InteractiveToken"))
    cases.append(("schtasks good: time limit", good["execution_time_limit"], "PT0S"))
    cases.append(("schtasks good: batteries", good["disallow_start_if_on_batteries"], False))
    cases.append(("schtasks good: user", good["user_id"], "DESK-PC\\bosco"))
    cases.append(("schtasks good: checks", set(statuses(check_windows_task(good)).values()), {PASS}))

    # A real `schtasks /query /xml ONE` capture from the Windows box T3.8
    # installed on, kept next to the hand-written shape above rather than
    # replacing it: the two disagree in ways that are the point. Windows omits
    # <Enabled> at its default and renders the principal as a SID, neither of
    # which a fixture written from the documentation would have predicted.
    real = parse_schtasks_xml(fixture("windows_schtasks_real_capture.xml"))
    cases.append(("schtasks real capture: Enabled is omitted", real["enabled"], None))
    cases.append(("schtasks real capture: one LogonTrigger", real["triggers"], ["LogonTrigger"]))
    cases.append(("schtasks real capture: checks",
                  set(statuses(check_windows_task(real)).values()), {PASS}))

    bad = parse_schtasks_xml(fixture("windows_schtasks_bad_boot_trigger.xml"))
    cases.append(("schtasks bad: checks", statuses(check_windows_task(bad)), {
        "windows.task.exists": PASS,
        "windows.task.logon-trigger": FAIL,
        "windows.task.logon-type": FAIL,
        "windows.task.execution-time-limit": FAIL,
        "windows.task.batteries": FAIL,
        "windows.task.stop-on-battery": FAIL,
        "windows.task.enabled": PASS,
    }))

    cases.append(("schtasks enabled absent is a pass",
                  statuses(check_windows_task(dict(good, enabled=None)))["windows.task.enabled"],
                  PASS))
    cases.append(("schtasks enabled false fails",
                  statuses(check_windows_task(dict(good, enabled=False)))["windows.task.enabled"],
                  FAIL))

    absent = parse_schtasks_xml(fixture("windows_schtasks_absent.txt"))
    cases.append(("schtasks absent: found", absent["found"], False))
    cases.append(("schtasks absent: checks", statuses(check_windows_task(absent)),
                  {"windows.task.exists": FAIL}))
    cases.append(("schtasks garbage raises", _raises(parse_schtasks_xml, "not xml at all"), True))

    cases.append(("windows service present", detect_system_scope("win32", {
        "sc_query": captured(fixture("windows_sc_query_present.txt"))}).status, FAIL))
    cases.append(("windows service absent", detect_system_scope("win32", {
        "sc_query": captured(fixture("windows_sc_query_absent.txt"))}).status, PASS))
    cases.append(("windows service unreadable fails closed", detect_system_scope("win32", {
        "sc_query": unreadable("access denied")}).status, UNKNOWN))
    cases.append(("windows service not collected fails closed",
                  detect_system_scope("win32", {}).status, UNKNOWN))
    cases.append(("windows sc garbage fails closed", detect_system_scope("win32", {
        "sc_query": captured("something else entirely")}).status, UNKNOWN))

    cases.append(("windows autologin on", detect_autologin("win32", {
        "winlogon": captured(fixture("windows_reg_autologin_on.txt"))}).status, FAIL))
    cases.append(("windows autologin off", detect_autologin("win32", {
        "winlogon": captured(fixture("windows_reg_autologin_off.txt"))}).status, PASS))
    cases.append(("windows autologin unset", detect_autologin("win32", {
        "winlogon": captured(fixture("windows_reg_autologin_unset.txt"))}).status, PASS))
    cases.append(("windows autologin unreadable fails closed", detect_autologin("win32", {
        "winlogon": unreadable("reg.exe missing")}).status, UNKNOWN))
    # The locale-proof collector's two answers: absent is a pass, present is
    # read on its value alone. Neither one goes through an error string.
    cases.append(("windows autologin absent is a pass", detect_autologin("win32", {
        "winlogon": missing("no AutoAdminLogon value")}).status, PASS))
    cases.append(("windows autologin winreg shape parses", detect_autologin("win32", {
        "winlogon": captured("    AutoAdminLogon    REG_SZ    1")}).status, FAIL))

    # -- Linux ------------------------------------------------------------
    unit_good = parse_systemctl_show(fixture("linux_systemctl_show_user_good.txt"))
    cases.append(("systemd good: wanted by", unit_good["WantedBy"], "graphical-session.target"))
    cases.append(("systemd good: part of", unit_good["PartOf"], "graphical-session.target"))
    cases.append(("systemd good: type", unit_good["Type"], "exec"))
    cases.append(("systemd good: checks", set(statuses(check_systemd_user_unit(unit_good)).values()),
                  {PASS}))

    unit_default = parse_systemctl_show(fixture("linux_systemctl_show_user_default_target.txt"))
    cases.append(("systemd default.target: checks", statuses(check_systemd_user_unit(unit_default)), {
        "linux.unit.loaded": PASS,
        "linux.unit.type": FAIL,
        "linux.unit.wanted-by": FAIL,
        "linux.unit.part-of": FAIL,
        "linux.unit.enabled": PASS,
    }))

    unit_absent = parse_systemctl_show(fixture("linux_systemctl_show_user_absent.txt"))
    cases.append(("systemd absent: checks", statuses(check_systemd_user_unit(unit_absent)),
                  {"linux.unit.loaded": FAIL}))
    cases.append(("systemctl empty raises", _raises(parse_systemctl_show, "\n\n"), True))

    closure_good = parse_list_dependencies(fixture("linux_list_dependencies_default_good.txt"))
    closure_bad = parse_list_dependencies(fixture("linux_list_dependencies_default_bad.txt"))
    cases.append(("closure good: unit absent", UNIT_NAME in closure_good, False))
    cases.append(("closure good: parses real names", "basic.target" in closure_good, True))
    graphical = parse_list_dependencies(
        fixture("linux_list_dependencies_graphical_session.txt"))
    cases.append(("closure: escaped unit names survive",
                  any(name.startswith("app-geoclue") for name in graphical), True))
    cases.append(("closure bad: unit present", UNIT_NAME in closure_bad, True))
    cases.append(("closure good: check", check_not_in_default_closure(closure_good).status, PASS))
    cases.append(("closure bad: check", check_not_in_default_closure(closure_bad).status, FAIL))

    cases.append(("sddm autologin off", detect_autologin("linux", {
        "sddm": captured(fixture("linux_sddm_autologin_off.conf"))}).status, PASS))
    cases.append(("sddm autologin on", detect_autologin("linux", {
        "sddm": captured(fixture("linux_sddm_autologin_on.conf"))}).status, FAIL))
    cases.append(("gdm autologin on", detect_autologin("linux", {
        "gdm": captured(fixture("linux_gdm_autologin_on.conf"))}).status, FAIL))
    cases.append(("gdm autologin off", detect_autologin("linux", {
        "gdm": captured(fixture("linux_gdm_autologin_off.conf"))}).status, PASS))
    cases.append(("lightdm autologin on", detect_autologin("linux", {
        "lightdm": captured(fixture("linux_lightdm_autologin_on.conf"))}).status, FAIL))
    cases.append(("linux autologin, no display manager fails closed", detect_autologin("linux", {
        "gdm": missing(), "sddm": missing(), "lightdm": missing()}).status, UNKNOWN))
    cases.append(("linux autologin unreadable fails closed", detect_autologin("linux", {
        "sddm": unreadable("permission denied")}).status, UNKNOWN))

    clean_linux = {
        "systemd_system": captured(fixture("linux_systemctl_show_system_absent.txt")),
        "crontab": captured(fixture("linux_crontab_clean.txt")),
        "docker_ps": missing("docker is not installed"),
    }
    cases.append(("linux system scope clean", detect_system_scope("linux", clean_linux).status, PASS))
    cases.append(("linux system unit present", detect_system_scope("linux", dict(
        clean_linux, systemd_system=captured(
            fixture("linux_systemctl_show_user_good.txt")))).status, FAIL))
    cases.append(("linux @reboot present", detect_system_scope("linux", dict(
        clean_linux, crontab=captured(fixture("linux_crontab_reboot.txt")))).status, FAIL))
    cases.append(("linux container running", detect_system_scope("linux", dict(
        clean_linux, docker_ps=captured(fixture("linux_docker_ps_running.txt")))).status, FAIL))
    cases.append(("linux docker clean", detect_system_scope("linux", dict(
        clean_linux, docker_ps=captured(fixture("linux_docker_ps_clean.txt")))).status, PASS))
    cases.append(("linux system scope unreadable fails closed", detect_system_scope("linux", dict(
        clean_linux, systemd_system=unreadable("dbus refused"))).status, UNKNOWN))
    cases.append(("linux crontab unreadable fails closed", detect_system_scope("linux", dict(
        clean_linux, crontab=unreadable("permission denied"))).status, UNKNOWN))

    cases.append(("wsl: native kernel", detect_wsl("linux", {
        "osrelease": captured(fixture("linux_osrelease_native.txt"))}).status, PASS))
    cases.append(("wsl: wsl kernel", detect_wsl("linux", {
        "osrelease": captured(fixture("linux_osrelease_wsl.txt"))}).status, FAIL))
    cases.append(("wsl: env marker", detect_wsl("linux", {
        "osrelease": captured(fixture("linux_osrelease_native.txt")),
        "env": captured("WSL_DISTRO_NAME=Ubuntu")}).status, FAIL))
    cases.append(("wsl: unreadable fails closed", detect_wsl("linux", {
        "osrelease": unreadable("/proc not mounted")}).status, UNKNOWN))
    cases.append(("wsl: not applicable off Linux", detect_wsl("win32", {}).status, PASS))

    host_container = {
        "detect_virt": captured(fixture("linux_detect_virt_host.txt")),
        "dockerenv": missing(),
        "containerenv": missing(),
        "cgroup": captured(fixture("linux_cgroup_v2_host.txt")),
        "env_container": captured(""),
    }
    cases.append(("container: bare host", detect_container("linux", host_container).status, PASS))
    cases.append(("container: detect-virt docker", detect_container("linux", dict(
        host_container, detect_virt=captured(
            fixture("linux_detect_virt_docker.txt")))).status, FAIL))
    cases.append(("container: dockerenv marker", detect_container("linux", dict(
        host_container, detect_virt=missing(),
        dockerenv=captured("/.dockerenv"))).status, FAIL))
    cases.append(("container: cgroup v1 docker", detect_container("linux", dict(
        host_container, detect_virt=missing(),
        cgroup=captured(fixture("linux_cgroup_v1_docker.txt")))).status, FAIL))
    cases.append(("container: $container set", detect_container("linux", dict(
        host_container, env_container=captured("podman"))).status, FAIL))
    cases.append(("container: no detect-virt, cgroup v2 fails closed", detect_container("linux", dict(
        host_container, detect_virt=missing())).status, UNKNOWN))

    # -- macOS ------------------------------------------------------------
    agent = parse_launchctl_print(fixture("macos_launchctl_print_agent.txt"))
    cases.append(("launchctl agent: type", agent["type"], "LaunchAgent"))
    cases.append(("launchctl agent: domain", agent["domain"], "gui/501"))
    cases.append(("launchctl agent: properties",
                  "runatload" in agent["properties"], True))
    cases.append(("launchctl agent: path not shadowed by env block",
                  agent["path"], "/Users/bosco/Library/LaunchAgents/dev.bosco.deskpanel.plist"))
    daemon = parse_launchctl_print(fixture("macos_launchctl_print_daemon.txt"))
    cases.append(("launchctl daemon: type", daemon["type"], "LaunchDaemon"))
    cases.append(("launchctl daemon: domain", daemon["domain"], "system"))
    not_loaded = parse_launchctl_print(fixture("macos_launchctl_print_absent.txt"))
    cases.append(("launchctl absent: found", not_loaded["found"], False))
    cases.append(("launchctl garbage raises", _raises(parse_launchctl_print, "hello"), True))

    plist_good = parse_launchagent_plist(fixture("macos_launchagent_good.plist"))
    cases.append(("plist good: session type", plist_good["LimitLoadToSessionType"], "Aqua"))
    user_agents = Path("/Users/bosco/Library/LaunchAgents/dev.bosco.deskpanel.plist")
    cases.append(("macos good: checks",
                  set(statuses(check_macos_agent(plist_good, agent, user_agents)).values()), {PASS}))

    plist_bad = parse_launchagent_plist(fixture("macos_launchagent_no_session_type.plist"))
    cases.append(("macos unset session type: checks",
                  statuses(check_macos_agent(plist_bad, agent, user_agents)), {
                      "macos.agent.exists": PASS,
                      "macos.agent.location": PASS,
                      "macos.agent.session-type": FAIL,
                      "macos.agent.run-at-load": FAIL,
                      "macos.agent.loaded": PASS,
                  }))
    cases.append(("macos plist in /Library fails", statuses(check_macos_agent(
        plist_good, agent,
        Path("/Library/LaunchAgents/dev.bosco.deskpanel.plist")))["macos.agent.location"], FAIL))
    cases.append(("macos agent missing", statuses(check_macos_agent(None, None, user_agents)),
                  {"macos.agent.exists": FAIL}))
    cases.append(("macos agent not loaded", statuses(check_macos_agent(
        plist_good, not_loaded, user_agents))["macos.agent.loaded"], FAIL))
    cases.append(("macos launchctl not captured fails closed", statuses(check_macos_agent(
        plist_good, None, user_agents))["macos.agent.loaded"], UNKNOWN))

    clean_macos = {"launchdaemon_files": captured(""),
                   "launchctl_system": captured(fixture("macos_launchctl_print_absent.txt"))}
    cases.append(("macos system scope clean",
                  detect_system_scope("darwin", clean_macos).status, PASS))
    cases.append(("macos launchdaemon file", detect_system_scope("darwin", dict(
        clean_macos,
        launchdaemon_files=captured("/Library/LaunchDaemons/dev.bosco.deskpanel.plist"))).status,
        FAIL))
    cases.append(("macos loaded in system domain", detect_system_scope("darwin", dict(
        clean_macos,
        launchctl_system=captured(fixture("macos_launchctl_print_daemon.txt")))).status, FAIL))
    cases.append(("macos system scope unreadable fails closed", detect_system_scope("darwin", {
        "launchdaemon_files": unreadable("operation not permitted")}).status, UNKNOWN))

    cases.append(("macos autologin on", detect_autologin("darwin", {
        "loginwindow": captured(fixture("macos_defaults_autologin_on.txt"))}).status, FAIL))
    cases.append(("macos autologin absent", detect_autologin("darwin", {
        "loginwindow": captured(fixture("macos_defaults_autologin_absent.txt"))}).status, PASS))
    cases.append(("macos autologin unreadable fails closed", detect_autologin("darwin", {
        "loginwindow": unreadable("defaults missing")}).status, UNKNOWN))

    # -- the exit code itself ---------------------------------------------
    cases.append(("exit code: all pass", exit_code([Check("a", PASS, "")]), 0))
    cases.append(("exit code: a failure", exit_code([Check("a", PASS, ""), Check("b", FAIL, "")]), 1))
    cases.append(("exit code: an unknown", exit_code([Check("a", PASS, ""), Check("b", UNKNOWN, "")]), 2))
    cases.append(("exit code: failure beats unknown",
                  exit_code([Check("a", UNKNOWN, ""), Check("b", FAIL, "")]), 1))
    cases.append(("exit code: nothing checked", exit_code([]), 2))
    cases.append(("unsupported platform fails closed",
                  run_checks("aix7")[0].status, UNKNOWN))

    return cases


def _raises(function, argument):
    try:
        function(argument)
    except ParseError:
        return True
    return False


def self_test(stream=sys.stdout):
    if not FIXTURE_DIR.is_dir():
        print(f"fixture directory {FIXTURE_DIR} is missing", file=stream)
        return 2
    try:
        cases = self_test_cases()
    except (ParseError, OSError, KeyError) as exc:
        print(f"self-test could not run: {type(exc).__name__}: {exc}", file=stream)
        return 2

    failures = 0
    for label, actual, expected in cases:
        if actual != expected:
            failures += 1
            print(f"FAIL {label}\n  expected: {expected!r}\n  actual:   {actual!r}", file=stream)
    print(f"{len(cases) - failures}/{len(cases)} self-test cases passed", file=stream)
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify that desk-panel's autostart is scoped to a graphical login session.")
    parser.add_argument("--self-test", action="store_true", dest="self_test",
                        help="run the parsers against the bundled fixtures and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    checks = run_checks()
    print(format_report(checks))
    return exit_code(checks)


if __name__ == "__main__":
    sys.exit(main())
