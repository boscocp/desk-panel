"""The closed catalogue of things the panel may do to this PC.

[ADR 0015](../docs/adr/0015-the-panel-can-act-on-the-pc.md) is the decision;
this is the implementation, and the two have to be read together. The short
version: the request carries an **id and nothing else**, the id is a key in the
table below and is never interpolated into anything, and every entry has to be
safe to repeat because anyone on the LAN can repeat it.

No HTTP and no Android here, and nothing imported from `server.server` -- this
module is pure enough to unit test the way `config_format.py` is, with the
runner injected so a test never executes a mixer command.

Standard library only, like the rest of `server/`.
"""

import shutil
import subprocess
import sys

# Two seconds is generous for a local mixer call. It matters because this
# process is the login signal: a blocked action thread sitting on a worker
# while `/ping` queues behind it is invariant 2 failing, and the phone flips
# to OFFLINE on a single missed ping (see `Server`'s docstring).
TIMEOUT_S = 2.0

MUTED, UNMUTED, UNKNOWN = "muted", "unmuted", "unknown"

# Every id this server will ever answer to. Config says which of these are
# *enabled*; it can never add one, which is the half of ADR 0015 that makes a
# missing authentication layer defensible.
CATALOGUE = ("mute-audio", "mute-mic")


class ActionError(Exception):
    """A command that ran and did not work. Carries what the log should say."""


class Unsupported(Exception):
    """This platform has no implementation. A 501, not a 500."""


# --------------------------------------------------------------------------
# The table. Pure data: id -> platform -> a list of argument lists to try in
# order. A list and not a string, everywhere, with no placeholder in any
# element -- there is nothing for a request to reach.
# --------------------------------------------------------------------------

_MACOS_OUTPUT_TOGGLE = (
    "set volume output muted not (output muted of (get volume settings))"
)

# Input has no toggle in the `volume settings` API, so this reads the current
# input volume and swaps it with a remembered one. Muting to 0 and unmuting to
# 100 would be the obvious cut and is wrong: it hands back somebody's
# carefully set microphone level as a shout.
#
# The remembered level lives in `dev.bosco.deskpanel`'s preferences, which is
# the only place an osascript invocation can keep state that survives the next
# one -- and it survives a server restart too, which storing it in this
# process would not.
#
# **This is the one command in the table that contains a shell.** It is a
# literal in this file from end to end: the only value concatenated into it is
# an integer AppleScript itself read from the audio API, and nothing from the
# request is anywhere near it (ADR 0015). Reaching for `defaults` through a
# separate argv instead would mean two commands per press and a state machine
# in Python to sequence them, which is more moving parts guarding a constant.
_MACOS_INPUT_TOGGLE = (
    'set prev to 0\n'
    'try\n'
    '    set prev to (do shell script '
    '"defaults read dev.bosco.deskpanel inputVolume 2>/dev/null || echo 0") as integer\n'
    'end try\n'
    'set current to input volume of (get volume settings)\n'
    'if current > 0 then\n'
    '    do shell script "defaults write dev.bosco.deskpanel inputVolume -int " & current\n'
    '    set volume input volume 0\n'
    '    return "muted"\n'
    'else\n'
    '    if prev is 0 then set prev to 75\n'
    '    set volume input volume prev\n'
    '    return "unmuted"\n'
    'end if'
)

# Core Audio through Add-Type, because the usual answer is nircmd and that is a
# download the owner has to trust. `eRender` is 0 and `eCapture` is 1 in
# EDataFlow; `eMultimedia` is 1 in ERole. The C# is a literal in this file and
# nothing from the request reaches it.


def _windows_toggle(data_flow):
    source = (
        "Add-Type -Language CSharp -TypeDefinition @'\n"
        "using System.Runtime.InteropServices;\n"
        "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "interface IAudioEndpointVolume {\n"
        "  int f();int g();int h();int i();int j();int k();int l();int m();\n"
        "  int SetMute(bool m,System.Guid c);\n"
        "  int GetMute(out bool m);\n"
        "}\n"
        "[Guid(\"D666063F-1587-4E43-81F1-B948E807363F\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "interface IMMDevice {\n"
        "  int Activate(ref System.Guid id,int ctx,System.IntPtr p,"
        "out IAudioEndpointVolume ep);\n"
        "}\n"
        "[Guid(\"A95664D2-9614-4F35-A746-DE8DB63617E6\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "interface IMMDeviceEnumerator {\n"
        "  int f();\n"
        "  int GetDefaultAudioEndpoint(int flow,int role,out IMMDevice dev);\n"
        "}\n"
        "[ComImport,Guid(\"BCDE0395-E52F-467C-8E3D-C4579291692E\")]\n"
        "class MMDeviceEnumeratorComObject {}\n"
        "public class Endpoint {\n"
        "  public static string Toggle(int flow) {\n"
        "    var e=(IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());\n"
        "    IMMDevice dev; e.GetDefaultAudioEndpoint(flow,1,out dev);\n"
        "    var iid=typeof(IAudioEndpointVolume).GUID;\n"
        "    IAudioEndpointVolume ep; dev.Activate(ref iid,23,System.IntPtr.Zero,out ep);\n"
        "    bool muted; ep.GetMute(out muted);\n"
        "    ep.SetMute(!muted,System.Guid.Empty);\n"
        "    return muted ? \"unmuted\" : \"muted\";\n"
        "  }\n"
        "}\n"
        "'@\n"
        f"[Endpoint]::Toggle({data_flow})"
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", source]


# id -> platform key -> candidate argument lists, tried in order until one of
# the executables exists. The fallback is a *second binary*, never a shell `||`.
_TABLE = {
    "mute-audio": {
        "linux": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
        ],
        "darwin": [["osascript", "-e", _MACOS_OUTPUT_TOGGLE]],
        "win32": [_windows_toggle(0)],
    },
    "mute-mic": {
        "linux": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
            ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"],
        ],
        "darwin": [["osascript", "-e", _MACOS_INPUT_TOGGLE]],
        "win32": [_windows_toggle(1)],
    },
}


def platform_key(platform):
    """Pure: `sys.platform` reduced to the three families the table knows.

    `linux2`, `freebsd14` and friends collapse to `linux`, which is where the
    PipeWire and PulseAudio commands live and is right for every one of them.
    Anything else keeps its own name and finds no entry, which is a 501.
    """
    if platform.startswith("linux") or platform.startswith("freebsd"):
        return "linux"
    if platform == "darwin":
        return "darwin"
    if platform in {"win32", "cygwin", "msys"}:
        return "win32"
    return platform


def candidates(action, platform=None):
    """Pure: the argument lists for `action` on `platform`, best first.

    Raises `KeyError` for an id outside the catalogue -- callers check
    membership first, and reaching here with an unknown id is a bug, not a
    request.
    """
    if action not in CATALOGUE:
        raise KeyError(action)
    return list(_TABLE[action].get(platform_key(platform or sys.platform), []))


def enabled_actions(raw):
    """Pure: the validated list of enabled ids, or raise `ValueError`.

    `raw` is whatever `config["actions"]` holds. The message is the whole
    value of this function: it is printed at startup with a console in front
    of the owner, which is the one moment a typo is cheap to fix.

    An empty **table** is accepted as "nothing enabled". `config.example.toml`
    shipped `[actions]` as a reserved stub and installed configs have it, so
    refusing it would turn a pull into a server that will not start -- which
    is the failure T3.13 exists to prevent, arriving from the direction that
    task cannot see.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        if not raw:
            return []
        raise ValueError(
            "config: `actions` is a list of names now, not a table -- write "
            'actions = ["mute-audio", "mute-mic"] and see ADR 0015'
        )
    if not isinstance(raw, list):
        raise ValueError(f"config: `actions` must be a list of names, not {type(raw).__name__}")

    enabled = []
    for name in raw:
        if not isinstance(name, str):
            raise ValueError(f"config: `actions` holds {name!r}, which is not a name")
        if name not in CATALOGUE:
            raise ValueError(
                f"config: `actions` names {name!r}, which this server has no "
                f"implementation for. Known actions: {', '.join(CATALOGUE)}"
            )
        if name not in enabled:
            enabled.append(name)
    return enabled


def state_from(action, stdout, returncode):
    """Pure: the state a finished command reports, or `unknown`.

    `wpctl` and `pactl` print nothing and there is nothing to infer, so the
    honest answer for a toggle on Linux is `unknown` -- a state this server
    guessed is exactly what ADR 0015 says a button must never show.
    """
    if returncode != 0:
        return UNKNOWN
    text = (stdout or "").strip().lower()
    if text in {MUTED, UNMUTED}:
        return text
    # osascript's output toggle prints the boolean it set, not a word.
    if text in {"true", "missing value"}:
        return MUTED
    if text == "false":
        return UNMUTED
    return UNKNOWN


def describe(enabled, platform=None, which=None):
    """One line per enabled action: what it will actually run, or that it cannot.

    Printed at startup (T8.1 step 4). Without it, a machine with neither
    `wpctl` nor `pactl` installed looks identical to a working one until
    somebody presses a button and nothing happens -- and "nothing happened" is
    the hardest failure on this whole project to diagnose from the desk.
    """
    which = which or shutil.which
    lines = []
    for action in enabled:
        options = candidates(action, platform)
        found = next((option for option in options if which(option[0])), None)
        if found is None:
            wanted = ", ".join(sorted({option[0] for option in options})) or "nothing"
            lines.append(f"  {action}: no command available (looked for {wanted}) -- will answer 501")
        else:
            lines.append(f"  {action}: {found[0]}")
    return lines


def _default_runner(argv, timeout):
    """The only place this module touches the machine.

    An argument **list**, and no shell keyword at all. T8.1 asserts that
    through the AST rather than by grepping for the literal, because a grep
    for it passes against the same keyword written with spaces around the
    equals sign -- and the acceptance also greps this directory for that
    literal, so writing it out here would fail the build on a comment.
    """
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def run_action(action, platform=None, runner=None, which=None, timeout=TIMEOUT_S):
    """Execute `action`. Returns a state; raises `Unsupported` or `ActionError`.

    `runner` and `which` are injected so the tests can assert on the argument
    list without a mixer, a desktop session or a subprocess.
    """
    runner = runner or _default_runner
    which = which or shutil.which

    options = candidates(action, platform)
    argv = next((option for option in options if which(option[0])), None)
    if argv is None:
        missing = ", ".join(sorted({option[0] for option in options})) or "no command"
        raise Unsupported(
            f"{action} is not available on this platform ({platform or sys.platform}): {missing}"
        )

    try:
        done = runner(argv, timeout)
    except subprocess.TimeoutExpired:
        # A timeout is a failure and not a hang. Saying so keeps the worker
        # free for /ping, which is the signal this whole process exists to be.
        raise ActionError(f"{argv[0]} did not finish within {timeout:g}s") from None
    except OSError as exc:
        raise ActionError(f"{argv[0]} could not be started: {exc}") from None

    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise ActionError(
            f"{argv[0]} exited {done.returncode}: {detail[-1][:200] if detail else 'no output'}"
        )
    return state_from(action, done.stdout, done.returncode)
