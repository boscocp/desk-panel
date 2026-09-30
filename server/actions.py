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

import os
import re
import shutil
import subprocess
import sys

# Two seconds is generous for a local mixer call. It matters because this
# process is the login signal: a blocked action thread sitting on a worker
# while `/ping` queues behind it is invariant 2 failing, and the phone flips
# to OFFLINE on a single missed ping (see `Server`'s docstring).
TIMEOUT_S = 2.0

# Windows is the exception, and not by a little. `Add-Type -TypeDefinition`
# compiles that C# with the real compiler on **every** press -- the process
# exits, so nothing is cached between them -- and `powershell -NoProfile` has
# to start first. Two seconds is not enough for that on any machine, so the
# whole platform would answer 500 on a timeout every time. It is still a
# bound and still a failure rather than a hang, which is what invariant 2
# needs; a request thread of its own is holding it, not a shared worker.
WINDOWS_TIMEOUT_S = 15.0

MUTED, UNMUTED, UNKNOWN = "muted", "unmuted", "unknown"

# Every id this server will ever answer to. Config says which of these are
# *enabled*; it can never add one, which is the half of ADR 0015 that makes a
# missing authentication layer defensible.
# The two buttons: each press flips a mute and reports what the mixer holds.
TOGGLES = ("mute-audio", "mute-mic")

CATALOGUE = TOGGLES + ("volume",)

# The one action that carries a value (T8.4, ADR 0015's third amendment): the
# PC's output volume, as a whole percentage. `parse_level` turns the request's
# text into an int from 0 to 100 before anything else sees it, and only that
# int, formatted by this module, reaches a command. Setting a volume is safe
# to repeat in the ADR's sense: the second identical request changes nothing.
VOLUME = "volume"


class ActionError(Exception):
    """A command that ran and did not work. Carries what the log should say."""


class Unsupported(Exception):
    """This platform has no implementation. A 501, not a 500."""


# --------------------------------------------------------------------------
# The table. Pure data: id -> platform -> a list of argument lists to try in
# order. A list and not a string, everywhere, with no placeholder in any
# element -- there is nothing for a request to reach.
# --------------------------------------------------------------------------

# `set volume output muted ...` is a command that returns no result, so an
# osascript that ends on it prints nothing and every press would report
# `unknown`. The word is said explicitly instead, the way the input toggle
# below already does -- the state in the response is the state the command
# observed, which is the only kind ADR 0015 allows a button to show.
_MACOS_OUTPUT_TOGGLE = (
    'set wanted to not (output muted of (get volume settings))\n'
    'set volume output muted wanted\n'
    'if wanted then\n'
    '    return "muted"\n'
    'else\n'
    '    return "unmuted"\n'
    'end if'
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
#
# The microphone is toggled on **every active capture endpoint**, not on the
# default one. The first run on the Windows box (2026-09-26) had three live
# inputs -- the default, a headset and Steam's virtual one -- and the button
# muted the default while the owner was talking into the headset: a 200, a
# cross on the button, and a live microphone. That is the one failure ADR 0015
# calls worse than no button. The default decides the direction and every
# input follows it, so one press never leaves a mix of muted and live mics.
# Speakers keep the default-only toggle: sound from the wrong one is audible,
# a microphone left open is not.


def _windows_toggle(data_flow, every_endpoint=False):
    source = (
        "Add-Type -Language CSharp -TypeDefinition @'\n"
        "using System.Runtime.InteropServices;\n"
        "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        # Eleven placeholders, not eight, and the count is the whole thing
        # working: COM dispatches by vtable slot, so a short interface does
        # not fail, it calls the wrong method. `SetMute` is the *twelfth*
        # entry of `IAudioEndpointVolume` (endpointvolume.h) -- after the two
        # notify registrations, `GetChannelCount`, the four master-volume
        # calls and the four per-channel ones. Declaring eight would land
        # `SetMute` on `SetChannelVolumeLevelScalar`.
        "interface IAudioEndpointVolume {\n"
        "  int f();int g();int h();int i();int j();int k();\n"
        "  int l();int m();int n();int o();int p();\n"
        # `BOOL` is the 4-byte Win32 one; a bare C# `bool` on a COM interface
        # marshals as a 2-byte VARIANT_BOOL. And `pguidEventContext` is a
        # *pointer* that may be null, not a Guid by value.
        "  int SetMute([MarshalAs(UnmanagedType.Bool)] bool m,System.IntPtr c);\n"
        "  int GetMute([MarshalAs(UnmanagedType.Bool)] out bool m);\n"
        "}\n"
        "[Guid(\"D666063F-1587-4E43-81F1-B948E807363F\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "interface IMMDevice {\n"
        "  int Activate(ref System.Guid id,int ctx,System.IntPtr p,"
        "out IAudioEndpointVolume ep);\n"
        "}\n"
        "[Guid(\"A95664D2-9614-4F35-A746-DE8DB63617E6\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        # `EnumAudioEndpoints` is the first slot and `GetDefaultAudioEndpoint`
        # the second, so both are declared in order -- the same vtable rule as
        # above. `Item` is the second slot of IMMDeviceCollection.
        "interface IMMDeviceEnumerator {\n"
        "  int EnumAudioEndpoints(int flow,int mask,out IMMDeviceCollection c);\n"
        "  int GetDefaultAudioEndpoint(int flow,int role,out IMMDevice dev);\n"
        "}\n"
        "[Guid(\"0BD7A1BE-7A1A-44DB-8397-CC5392387B5E\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "interface IMMDeviceCollection {\n"
        "  int GetCount(out int n);\n"
        "  int Item(int i,out IMMDevice dev);\n"
        "}\n"
        "[ComImport,Guid(\"BCDE0395-E52F-467C-8E3D-C4579291692E\")]\n"
        "class MMDeviceEnumeratorComObject {}\n"
        # Every call goes through `Ok`. These methods return their HRESULT
        # rather than throwing it (an `int`-returning COM declaration keeps
        # PreserveSig), so an unchecked `SetMute` that failed on one input
        # would still end on "muted" -- a cross over a live microphone. A
        # thrown exception is the last statement's error, powershell exits 1,
        # and `run_action` reports the press as failed.
        "public class Endpoint {\n"
        "  static void Ok(int hr) { Marshal.ThrowExceptionForHR(hr); }\n"
        "  static IAudioEndpointVolume Volume(IMMDevice dev) {\n"
        "    var iid=typeof(IAudioEndpointVolume).GUID;\n"
        "    IAudioEndpointVolume ep; Ok(dev.Activate(ref iid,23,System.IntPtr.Zero,out ep));\n"
        "    return ep;\n"
        "  }\n"
        # Set, then read back. The word returned is what the mixer holds
        # afterwards on every endpoint touched, not what was asked of it.
        "  static void Set(IAudioEndpointVolume ep,bool want) {\n"
        "    Ok(ep.SetMute(want,System.IntPtr.Zero));\n"
        "    bool now; Ok(ep.GetMute(out now));\n"
        "    if (now!=want) throw new System.Exception(\"an endpoint did not take the mute\");\n"
        "  }\n"
        "  public static string Toggle(int flow,bool every) {\n"
        "    var e=(IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());\n"
        "    IMMDevice dev; Ok(e.GetDefaultAudioEndpoint(flow,1,out dev));\n"
        "    var ep=Volume(dev);\n"
        "    bool muted; Ok(ep.GetMute(out muted));\n"
        "    Set(ep,!muted);\n"
        "    if (every) {\n"
        # DEVICE_STATE_ACTIVE is 1: unplugged and disabled inputs are skipped,
        # since activating one fails and cannot capture anything anyway.
        "      IMMDeviceCollection all; Ok(e.EnumAudioEndpoints(flow,1,out all));\n"
        "      int n; Ok(all.GetCount(out n));\n"
        "      for (int i=0;i<n;i++) {\n"
        "        IMMDevice d; Ok(all.Item(i,out d));\n"
        "        Set(Volume(d),!muted);\n"
        "      }\n"
        "    }\n"
        "    return muted ? \"unmuted\" : \"muted\";\n"
        "  }\n"
        "}\n"
        "'@\n"
        f"[Endpoint]::Toggle({data_flow},${'true' if every_endpoint else 'false'})"
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", source]


# The one binary the Linux microphone press runs, named once. `which` gates
# the whole press on `_LINUX_SOURCES[0]`, so a second spelling of it further
# down would be a command nothing ever probed for.
_PACTL = "pactl"

# The first command of the Linux microphone press, and the binary the 501
# path probes for. It is a row of `_TABLE` because everything that reads that
# table -- `candidates`, `describe`, the Unsupported message -- needs to name
# a command, and this is the one the press begins with.
_LINUX_SOURCES = [_PACTL, "list", "short", "sources"]

# id -> platform key -> candidate argument lists, tried in order until one of
# the executables exists. The fallback is a *second binary*, never a shell `||`.
_TABLE = {
    # Only for `describe`, which asks which command exists: the volume is
    # run by set_volume, with its level, and never by run_action.
    "volume": {
        "linux": [["wpctl"], ["pactl"]],
        "darwin": [["osascript"]],
        "win32": [["powershell"]],
    },
    "mute-audio": {
        "linux": [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
        ],
        "darwin": [["osascript", "-e", _MACOS_OUTPUT_TOGGLE]],
        "win32": [_windows_toggle(0)],
    },
    "mute-mic": {
        # **Not one command on Linux**, and this row holds only the first of
        # them -- see `_linux_mic_press`. A press cannot know what to mute
        # until it has asked the mixer what inputs exist, so the argument
        # lists cannot all be written here; what a row can still be is the
        # command the press starts with, which is also exactly the binary to
        # probe for.
        #
        # `wpctl` is gone from this id, and from this id only. It has no verb
        # for "every source" -- `wpctl set-mute` takes one node -- so keeping
        # it as a fallback would mean a PipeWire box quietly back to muting
        # the default alone, which is the hole T8.3 exists to close. `pactl`
        # reaches PipeWire through `pipewire-pulse` and is the only
        # microphone command on Linux now; a machine with `wpctl` and no
        # `pactl` answers 501, and `describe` says so at startup rather than
        # at the first press. The speakers keep both, because sound from the
        # wrong sink is audible and a microphone left open is not.
        "linux": [_LINUX_SOURCES],
        "darwin": [["osascript", "-e", _MACOS_INPUT_TOGGLE]],
        "win32": [_windows_toggle(1, every_endpoint=True)],
    },
}


# What to run *after* a toggle to find out what actually happened, per id and
# per platform. Keyed exactly like _TABLE and read the same way.
#
# **Why this exists.** The first cut answered `unknown` on Linux, because
# `wpctl` and `pactl` print nothing when they toggle -- and ADR 0015 is right
# that a state this server guessed is the one thing a button must never show.
# Asked for from the chair: the button should carry a cross when the PC is
# muted. So the state is *measured* rather than guessed: a second, read-only
# command whose whole job is to say what the mixer now holds.
#
# It is a separate command and not a flag on the first because the toggle and
# the question are different things, and because a read that fails must not
# make a successful toggle look like a failure -- `run_action` treats a
# missing or unreadable read-back as `unknown` and keeps the 200.
#
# macOS and Windows need no entry: their toggles already end on a word.
_READBACK = {
    "mute-audio": {
        "linux": [
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
        ],
    },
    # `mute-mic` has no Linux entry any more and the absence is the point:
    # the state of the default source is not the state of the microphone. A
    # press measures every non-monitor input itself and reports `muted` only
    # when all of them are -- `_linux_mic_state`.
    "mute-mic": {},
    "volume": {},
}


def readback(action, platform=None):
    """Pure: the read-only commands that answer "is it muted now?", best first."""
    if action not in CATALOGUE:
        raise KeyError(action)
    table = _READBACK.get(action, {})
    return [list(argv) for argv in table.get(platform_key(platform or sys.platform), [])]


def state_from_readback(stdout):
    """Pure: `muted`/`unmuted`/`unknown` from a mixer's own report.

    Two spellings, because two mixers:

      wpctl get-volume  ->  `Volume: 0.40 [MUTED]`  /  `Volume: 0.40`
      pactl get-sink-mute -> `Mute: yes`            /  `Mute: no`

    Anything else is `unknown`, deliberately. This function is the only thing
    standing between a mixer's output and a cross drawn on a button, and the
    cross is about a microphone.
    """
    text = (stdout or "").strip().lower()
    if not text:
        return UNKNOWN
    if "[muted]" in text:
        return MUTED
    if text.startswith("volume:"):
        # wpctl prints the mute flag only when it is set, so a volume line
        # without it is the mixer saying "not muted" rather than saying
        # nothing.
        return UNMUTED
    if text.startswith("mute:"):
        value = text.split(":", 1)[1].strip()
        if value in {"yes", "true", "1"}:
            return MUTED
        if value in {"no", "false", "0"}:
            return UNMUTED
    return UNKNOWN


def capture_sources(stdout):
    """Pure: the names of the real inputs in `pactl list short sources`.

    Every output carries a `.monitor` source -- a loopback of what the
    speakers are playing -- and those are **skipped**. Muting one records
    silence into a screen capture and silences no person at all, which is a
    bug in the opposite direction from the one this function exists for.

    The line is `index<TAB>name<TAB>driver<TAB>sample spec<TAB>state`. Only
    the sample spec has spaces in it and it comes after the name, so taking
    the second whitespace-separated token is safe: PulseAudio source names
    have never contained one, and reading them this way survives a build that
    pads the columns instead of tabbing them.
    """
    names = []
    for line in (stdout or "").splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        name = fields[1]
        if name.endswith(".monitor") or name in names:
            continue
        names.append(name)
    return names


def state_from_sources(states):
    """Pure: one word for a handful of microphones.

    `muted` only when **every** input is, which is the whole of T8.3 in a
    line: a mix of muted and live inputs is not a muted microphone, and the
    cross on the button is a claim about exactly that. A mix answers
    `unknown` rather than picking a side, and the page renders `unknown` as
    no claim at all.
    """
    states = list(states)
    if not states:
        return UNKNOWN
    if all(state == MUTED for state in states):
        return MUTED
    if all(state == UNMUTED for state in states):
        return UNMUTED
    return UNKNOWN


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
    # A copy of each argument list too, not only of the list of them: a
    # shallow copy still hands the caller `_TABLE`'s own inner lists, and one
    # `.append()` on one of those would edit the catalogue for the process.
    return [list(option)
            for option in _TABLE[action].get(platform_key(platform or sys.platform), [])]


def timeout_for(platform=None):
    """Pure: the seconds a press on `platform` is allowed to take.

    One number everywhere would have to be the Windows number, and 15s is far
    too long to wait on a mixer call that takes milliseconds.
    """
    return WINDOWS_TIMEOUT_S if platform_key(platform or sys.platform) == "win32" else TIMEOUT_S


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
    # An AppleScript that ends on a boolean rather than a word still reads.
    # `missing value` does **not** belong in this list: it is AppleScript for
    # "the audio API would not say", and answering `muted` to it is inventing
    # the one state a button must never invent -- a microphone that reads
    # muted while it is live is a privacy failure, not a cosmetic one.
    if text == "true":
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

    `CREATE_NO_WINDOW` exists only on Windows and is the difference between a
    silent press and a console window flashing over whatever the owner is
    doing, every time -- the server is started by a Scheduled Task with no
    console of its own, so `powershell.exe` would allocate one.

    **`LC_ALL=C`, because the mixer's answers are parsed.** `pactl` binds the
    `pulseaudio` text domain, so `Mute: yes` is a translated string: on a
    desktop with language packs installed it is `Stumm: ja` or `Mudo: sim`,
    and `state_from_readback` reads it as `unknown`. The panel would draw no
    cross, and the Linux microphone press would be **one-directional** -- an
    unreadable state is not `muted`, so every press mutes and none of them
    ever unmutes again. The server inherits the environment of the graphical
    session (invariant 2), which is exactly the environment that has a
    language set. Forcing the child's locale is the whole fix and it costs
    nothing anywhere else: every string this module reads back is ASCII, and
    the words it matches on are the untranslated ones.
    """
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout,
        env=dict(os.environ, LC_ALL="C"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def run_action(action, platform=None, runner=None, which=None, timeout=None):
    """Execute `action`. Returns a state; raises `Unsupported` or `ActionError`.

    `runner` and `which` are injected so the tests can assert on the argument
    list without a mixer, a desktop session or a subprocess. `timeout`
    defaults to the platform's, which is not one number -- see `timeout_for`.
    """
    if action == VOLUME:
        raise ActionError("volume needs a level; it is run by set_volume")
    runner = runner or _default_runner
    which = which or shutil.which
    timeout = timeout_for(platform) if timeout is None else timeout

    options = candidates(action, platform)
    argv = next((option for option in options if which(option[0])), None)
    if argv is None:
        missing = ", ".join(sorted({option[0] for option in options})) or "no command"
        raise Unsupported(
            f"{action} is not available on this platform ({platform or sys.platform}): {missing}"
        )

    press = _SEQUENCES.get(action, {}).get(platform_key(platform or sys.platform))
    if press is not None:
        # This one is several commands, and which ones is not knowable until
        # the first has run. The `which` gate above still decided whether the
        # platform can act at all, because the row it read holds the press's
        # first command.
        return press(runner, timeout)

    done = _run_or_raise(argv, runner, timeout)
    state = state_from(action, done.stdout, done.returncode)
    if state == UNKNOWN:
        # The toggle worked and said nothing about the result, which is every
        # Linux mixer. Ask.
        state = _read_state(action, platform, runner, which, timeout)
    return state


def _run_or_raise(argv, runner, timeout):
    """One command, with every way it can fail turned into an `ActionError`.

    Shared by the single-command path and by the Linux microphone press, so a
    failure reads the same in the log wherever it happened.
    """
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
    return done


def _linux_mic_press(runner, timeout):
    """Mute or unmute **every** input on Linux, and measure what they hold.

    Four kinds of command, in this order, all of them `pactl`:

      1. `list short sources` -- the names, from the mixer. Never from the
         request, and the `.monitor` loopbacks dropped (`capture_sources`).
      2. `get-source-mute <name>` -- the direction, read from the inputs this
         press is about to touch.
      3. `set-source-mute <name> 0|1` -- per input.
      4. the read-back, per input (`_linux_mic_state`).

    **The direction comes from the inputs, not from `@DEFAULT_SOURCE@`**, and
    the difference is not a detail. Found by review of PR #39, where the
    first cut asked the default source: a machine whose default is a monitor
    -- a normal thing to set for screen recording -- has a default that is
    never in `names`, so its state never moves and the button becomes
    one-directional for ever. Worse, a machine where the default is muted and
    another input is live is precisely the mixed state this task exists to
    end, and asking the default there answers "already muted", so the press
    would have **opened every microphone in the machine**.

    `state_from_sources` decides instead, which is the same function that
    draws the cross: the press unmutes exactly when the panel would be
    showing one, and mutes in every other case -- a mix, or a mixer nobody
    could parse, included. Muting is the safe direction, and it is the only
    one that can be taken without knowing anything for certain.

    The per-command timeout is kept rather than replaced by a budget for the
    whole press: each request is served on a thread of its own, and the
    number of commands is the number of sound cards plugged into the machine
    -- seven on the desk this was written at, of which three are inputs.
    """
    listing = _run_or_raise(_LINUX_SOURCES, runner, timeout)
    names = capture_sources(listing.stdout)
    if not names:
        # A machine with no microphone. Answering `unmuted` would be a claim
        # about hardware that is not there, and answering `muted` would be
        # the privacy lie; that the press failed is simply true.
        raise ActionError("pactl listed no capture source to mute")

    before = state_from_sources(_linux_source_states(names, runner, timeout))
    flag = "0" if before == MUTED else "1"

    for name in names:
        try:
            _run_or_raise([_PACTL, "set-source-mute", name, flag], runner, timeout)
        except ActionError as exc:
            # Loudly, and with the input named. A press that muted two inputs
            # of three and answered `muted` is the exact lie T8.3 exists to
            # remove: a cross drawn over a live microphone.
            raise ActionError(f"{name} did not take the mute: {exc}") from None

    return _linux_mic_state(names, runner, timeout)


def _linux_source_states(names, runner, timeout):
    """What each input holds, before anything is set. Raises, unlike the
    read-back: a mixer that cannot answer the question is a mixer this press
    is not going to be able to act on either, and finding that out before
    changing half of them is the cheaper failure.
    """
    return [
        state_from_readback(
            _run_or_raise([_PACTL, "get-source-mute", name], runner, timeout).stdout)
        for name in names
    ]


def _linux_mic_state(names, runner, timeout):
    """What the inputs hold now, or `unknown`. Never raises.

    Same bargain as `_read_state`: the toggles already happened and the
    caller is owed its 200, so a read that fails decides only whether a cross
    is drawn.
    """
    states = []
    for name in names:
        try:
            done = runner([_PACTL, "get-source-mute", name], timeout)
        except (subprocess.TimeoutExpired, OSError):
            return UNKNOWN
        if done.returncode != 0:
            return UNKNOWN
        states.append(state_from_readback(done.stdout))
    return state_from_sources(states)


# id -> platform -> the whole press, for the ids that are more than one
# command. Keyed like `_TABLE` and consulted after it, so a platform with no
# command at all is still `Unsupported` before anything runs.
_SEQUENCES = {"mute-mic": {"linux": _linux_mic_press}}


def _read_state(action, platform, runner, which, timeout):
    """The mixer's own answer, or `unknown`. Never raises.

    A read-back that fails is not a failed action: the toggle already
    succeeded and the caller is owed its 200. All this decides is whether the
    panel draws a cross, and "I could not tell" is an answer the page knows
    how to render.
    """
    for argv in readback(action, platform):
        if not which(argv[0]):
            continue
        try:
            done = runner(argv, timeout)
        except (subprocess.TimeoutExpired, OSError):
            return UNKNOWN
        if done.returncode == 0:
            return state_from_readback(done.stdout)
        return UNKNOWN
    return UNKNOWN


# --- The output volume (T8.4, ADR 0015's third amendment) -------------------


def _windows_volume(level=None):
    """PowerShell that sets (when `level` is an int) and then reads the default
    output's master volume, printing it as a whole percentage.

    IAudioEndpointVolume's vtable, in order: RegisterControlChangeNotify,
    UnregisterControlChangeNotify, GetChannelCount, SetMasterVolumeLevel,
    **SetMasterVolumeLevelScalar** (slot 4), GetMasterVolumeLevel,
    **GetMasterVolumeLevelScalar** (slot 6). The placeholders keep the two
    real methods in their slots, as `_windows_toggle` does for SetMute.
    `level` is this module's own int, never the request's text.
    """
    setter = "" if level is None else (
        f"Ok(ep.SetMasterVolumeLevelScalar({int(level) / 100:.2f}f,System.IntPtr.Zero));")
    source = (
        "Add-Type -Language CSharp -TypeDefinition @'\n"
        "using System.Runtime.InteropServices;\n"
        "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\"),"
        "InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
        "interface IAudioEndpointVolume {\n"
        "  int f();int g();int h();int i();\n"
        "  int SetMasterVolumeLevelScalar(float level,System.IntPtr c);\n"
        "  int j();\n"
        "  int GetMasterVolumeLevelScalar(out float level);\n"
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
        "public class Volume {\n"
        "  static void Ok(int hr) { Marshal.ThrowExceptionForHR(hr); }\n"
        "  public static int Run() {\n"
        "    var e=(IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());\n"
        "    IMMDevice dev; Ok(e.GetDefaultAudioEndpoint(0,1,out dev));\n"
        "    var iid=typeof(IAudioEndpointVolume).GUID;\n"
        "    IAudioEndpointVolume ep; Ok(dev.Activate(ref iid,23,System.IntPtr.Zero,out ep));\n"
        f"    {setter}\n"
        "    float now; Ok(ep.GetMasterVolumeLevelScalar(out now));\n"
        "    return (int)System.Math.Round(now*100);\n"
        "  }\n"
        "}\n"
        "'@\n"
        "[Volume]::Run()"
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", source]


_MACOS_VOLUME_READ = "output volume of (get volume settings)"


def volume_commands(level=None, platform=None):
    """Pure: `[(set_argv or None, read_argv)]` for this platform, best first.

    With `level` None it is a read alone. The level is formatted here from an
    int -- `0.42`, `42%`, `42` -- and never copied from a request.
    """
    key = platform_key(platform or sys.platform)
    if level is not None:
        level = int(level)
        if not 0 <= level <= 100:
            raise ValueError(f"volume level {level} is outside 0-100")
    if key == "linux":
        return [
            (None if level is None else
             ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level / 100:.2f}"],
             ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]),
            (None if level is None else
             ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
             ["pactl", "get-sink-volume", "@DEFAULT_SINK@"]),
        ]
    if key == "darwin":
        script = _MACOS_VOLUME_READ if level is None else (
            f"set volume output volume {level}\nreturn {_MACOS_VOLUME_READ}")
        return [(None, ["osascript", "-e", script])]
    if key == "win32":
        return [(None, _windows_volume(level))]
    return []


def parse_level(text):
    """Pure: a request's level -> int 0..100, or None. ASCII digits, 1-3 of them."""
    if not isinstance(text, str) or not text.isascii() or not text.isdigit() \
            or not 1 <= len(text) <= 3:
        return None
    level = int(text)
    return level if level <= 100 else None


def level_from(stdout):
    """Pure: a mixer's report -> whole percent 0..100, or None.

    Three spellings, because three mixers:
      wpctl get-volume       ->  `Volume: 0.42`, maybe ` [MUTED]`, above 1.00 when boosted
      pactl get-sink-volume  ->  `Volume: front-left: 27525 /  42% / -22.6 dB, ...`
      osascript, PowerShell  ->  `42`
    Anything else is None, and the bar then draws no level rather than a guess.
    """
    text = (stdout or "").strip()
    percent = re.search(r"(\d+)%", text)
    if percent:
        value = int(percent.group(1))
    elif re.fullmatch(r"Volume:\s*\d+\.\d+(\s*\[MUTED\])?", text):
        value = round(float(text.split(":", 1)[1].split()[0]) * 100)
    elif re.fullmatch(r"\d{1,3}", text):
        value = int(text)
    else:
        return None
    return max(0, min(100, value))


def set_volume(level, platform=None, runner=None, which=None, timeout=None):
    """Set the output volume, then return what the mixer holds (or None).

    Raises `Unsupported` (no mixer here) or `ActionError` (it ran and failed),
    like `run_action`. `level` is an int from `parse_level`, never raw text.
    """
    return _volume(level, platform, runner, which, timeout)


def read_volume(platform=None, runner=None, which=None, timeout=None):
    """The output volume now, or None. Never raises: it only draws a bar."""
    try:
        return _volume(None, platform, runner, which, timeout)
    except (Unsupported, ActionError, ValueError):
        return None


def _volume(level, platform, runner, which, timeout):
    runner = runner or _default_runner
    which = which or shutil.which
    timeout = timeout_for(platform) if timeout is None else timeout
    for setter, reader in volume_commands(level, platform):
        if not which(reader[0]):
            continue
        if setter is not None:
            _run_or_raise(setter, runner, timeout)
        return level_from(_run_or_raise(reader, runner, timeout).stdout)
    raise Unsupported(f"volume is not available on this platform ({platform or sys.platform})")
