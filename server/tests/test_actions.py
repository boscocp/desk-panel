"""The one route that changes the machine the server runs on.

[ADR 0015](../../docs/adr/0015-the-panel-can-act-on-the-pc.md) is what these
assert. Nothing here executes a mixer command: the runner is injected, and
several of these tests are about the runner **not** being called at all, which
is why they assert on a call count rather than only on a status code. A test
that only checks the response cannot tell 404-after-spawning from
404-before-spawning, and the difference is the whole endpoint.
"""
import subprocess
import sys
import unittest

from server import actions
from server.server import App, route


class FakeRunner:
    """Records what it was asked to run and answers with a canned result."""

    def __init__(self, returncode=0, stdout="", stderr="", raises=None):
        self.calls = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.raises = raises

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def always_present(_name):
    return "/usr/bin/fake"


def never_present(_name):
    return None


class CatalogueTests(unittest.TestCase):
    def test_every_command_is_an_argument_list_never_a_string(self):
        # A string would be a shell invocation waiting to happen. Asserted for
        # every id on every platform the table knows, so a future entry cannot
        # be added as a string without this failing.
        for action in actions.CATALOGUE:
            for platform in ("linux", "darwin", "win32"):
                for argv in actions.candidates(action, platform):
                    self.assertIsInstance(argv, list, f"{action}/{platform}")
                    for part in argv:
                        self.assertIsInstance(part, str, f"{action}/{platform}")

    def test_the_id_itself_never_appears_in_the_command(self):
        # The direct statement of ADR 0015: the id is a **key**, not a value.
        # If it appeared in an argument list, then something derived from the
        # request would be reaching a command line -- which is the one thing
        # this endpoint promises never to do.
        #
        # A `{}` or `%s` scan was the first cut of this and it was a bad
        # proxy: the Windows command is C#, which is full of braces, and the
        # test failed on `class MMDeviceEnumeratorComObject {}`.
        for action in actions.CATALOGUE:
            for platform in ("linux", "darwin", "win32"):
                for argv in actions.candidates(action, platform):
                    for part in argv:
                        self.assertNotIn(action, part, f"{action}/{platform}")

    def test_the_table_does_not_depend_on_anything_but_its_two_arguments(self):
        # Called twice, equal twice. A table assembled from the environment,
        # the clock or the config would not be, and this is the property that
        # makes reading `_TABLE` once enough to know what can ever run.
        for action in actions.CATALOGUE:
            for platform in ("linux", "darwin", "win32"):
                self.assertEqual(
                    actions.candidates(action, platform),
                    actions.candidates(action, platform),
                )

    def test_a_caller_cannot_mutate_the_table_through_what_it_is_handed(self):
        # `candidates` returns a copy. Without it, one caller appending to the
        # list it got would extend the catalogue for the whole process.
        got = actions.candidates("mute-audio", "linux")
        got.append(["rm", "-rf", "/"])
        self.assertEqual(len(actions.candidates("mute-audio", "linux")), 2)

    def test_the_copy_reaches_the_argument_lists_and_not_only_the_list_of_them(self):
        # A shallow copy passes the test above and still hands out `_TABLE`'s
        # own inner lists: one `.append()` on one of those edits the command
        # every later press will run, for the life of the process.
        actions.candidates("mute-audio", "linux")[0].append("--boom")
        self.assertNotIn("--boom", actions.candidates("mute-audio", "linux")[0])

    def test_windows_declares_every_vtable_slot_before_setmute(self):
        # COM dispatches by position, so a short interface does not fail --
        # it calls the wrong method. `SetMute` is the twelfth entry of
        # IAudioEndpointVolume, so eleven placeholders have to precede it or
        # muting the speakers sets a channel volume instead.
        argv, = actions.candidates("mute-audio", "win32")
        source = argv[-1]
        declarations = source.split("interface IAudioEndpointVolume {")[1]
        declarations = declarations.split("int SetMute")[0]
        self.assertEqual(declarations.count("();"), 11)

    def test_windows_mutes_every_microphone_and_only_the_default_speaker(self):
        # Measured on the Windows box: three live inputs, and a toggle of the
        # default alone left the headset the owner was talking into open while
        # the button showed a cross. Speakers stay default-only on purpose.
        mic, = actions.candidates("mute-mic", "win32")
        speakers, = actions.candidates("mute-audio", "win32")
        self.assertTrue(mic[-1].endswith("[Endpoint]::Toggle(1,$true)"))
        self.assertTrue(speakers[-1].endswith("[Endpoint]::Toggle(0,$false)"))

    def test_windows_enumerator_declares_its_slots_in_vtable_order(self):
        # Same rule as IAudioEndpointVolume: EnumAudioEndpoints is slot one,
        # GetDefaultAudioEndpoint slot two. Swapped, the default lookup would
        # call the enumeration with the wrong arguments.
        argv, = actions.candidates("mute-mic", "win32")
        body = argv[-1].split("interface IMMDeviceEnumerator {")[1].split("}")[0]
        self.assertLess(body.index("EnumAudioEndpoints"), body.index("GetDefaultAudioEndpoint"))
        self.assertEqual(body.count("\n  int "), 2)

    def test_windows_checks_every_hresult_it_is_handed(self):
        # `int`-returning COM methods hand back their HRESULT instead of
        # throwing it. One unchecked SetMute failing on one of three inputs
        # would still end on "muted" -- the lie the every-input change exists
        # to remove. Found by review of PR #37.
        for action in actions.CATALOGUE:
            argv, = actions.candidates(action, "win32")
            body = argv[-1].split("public class Endpoint {")[1]
            for call in ("SetMute(", "GetMute(", "Activate(", "GetDefaultAudioEndpoint(",
                         "EnumAudioEndpoints(", "GetCount(", "Item("):
                for line in body.splitlines():
                    if call in line:
                        self.assertIn("Ok(", line.split(call)[0][-12:], line)

    def test_an_id_outside_the_catalogue_raises_rather_than_returning_empty(self):
        # Empty would read as "this platform cannot", which is a different
        # answer with a different status code.
        with self.assertRaises(KeyError):
            actions.candidates("shutdown", "linux")

    def test_destructive_actions_are_not_in_the_catalogue(self):
        # ADR 0015: the threat model only holds for actions that are safe to
        # repeat. This is that decision, asserted.
        for name in ("shutdown", "reboot", "sleep", "lock", "logout"):
            self.assertNotIn(name, actions.CATALOGUE)

    def test_linux_falls_back_to_pulseaudio_after_pipewire(self):
        first, second = actions.candidates("mute-audio", "linux")
        self.assertEqual(first[0], "wpctl")
        self.assertEqual(second[0], "pactl")

    def test_the_microphone_has_no_wpctl_fallback_because_it_cannot_reach_every_input(self):
        # T8.3. `wpctl set-mute` takes one node and has no verb for "every
        # source", so keeping it as a fallback would put a PipeWire box
        # quietly back to muting the default alone -- the failure this id was
        # rewritten to remove. The speakers keep both mixers.
        commands = actions.candidates("mute-mic", "linux")
        self.assertEqual([argv[0] for argv in commands], ["pactl"])

    def test_platform_families_collapse_and_strangers_do_not(self):
        self.assertEqual(actions.platform_key("linux"), "linux")
        self.assertEqual(actions.platform_key("linux2"), "linux")
        self.assertEqual(actions.platform_key("freebsd14"), "linux")
        self.assertEqual(actions.platform_key("darwin"), "darwin")
        self.assertEqual(actions.platform_key("win32"), "win32")
        self.assertEqual(actions.platform_key("aix"), "aix")

    def test_an_unknown_platform_has_no_candidates(self):
        self.assertEqual(actions.candidates("mute-audio", "aix"), [])


class RunActionTests(unittest.TestCase):
    def test_the_first_present_command_is_the_one_that_runs(self):
        runner = FakeRunner()
        actions.run_action(
            "mute-audio", platform="linux", runner=runner,
            which=lambda name: "/usr/bin/pactl" if name == "pactl" else None,
        )
        # Two calls on Linux: the toggle, then the read-back that asks what it
        # did (see ReadbackTests). Both have to pick pactl -- a toggle through
        # PulseAudio and a question asked of PipeWire would be two mixers.
        self.assertEqual([call[0][0] for call in runner.calls], ["pactl", "pactl"])
        self.assertEqual(runner.calls[0][0][1], "set-sink-mute")
        self.assertEqual(runner.calls[1][0][1], "get-sink-mute")

    def test_no_command_present_is_unsupported_and_runs_nothing(self):
        runner = FakeRunner()
        with self.assertRaises(actions.Unsupported):
            actions.run_action("mute-audio", platform="linux", runner=runner, which=never_present)
        self.assertEqual(runner.calls, [])

    def test_an_unknown_platform_is_unsupported_and_runs_nothing(self):
        runner = FakeRunner()
        with self.assertRaises(actions.Unsupported):
            actions.run_action("mute-audio", platform="aix", runner=runner, which=always_present)
        self.assertEqual(runner.calls, [])

    def test_a_non_zero_exit_is_an_action_error(self):
        runner = FakeRunner(returncode=1, stderr="no such sink\n")
        with self.assertRaises(actions.ActionError) as caught:
            actions.run_action("mute-audio", platform="linux", runner=runner, which=always_present)
        self.assertIn("no such sink", str(caught.exception))

    def test_a_timeout_is_an_action_error_and_not_a_raise_through(self):
        runner = FakeRunner(raises=subprocess.TimeoutExpired("wpctl", 2.0))
        with self.assertRaises(actions.ActionError) as caught:
            actions.run_action("mute-audio", platform="linux", runner=runner, which=always_present)
        self.assertIn("did not finish", str(caught.exception))

    def test_a_missing_executable_at_spawn_is_an_action_error(self):
        # `which` said yes and exec still failed -- a race, or a broken
        # symlink. It is a failure, not a crash in a request thread.
        runner = FakeRunner(raises=OSError("Exec format error"))
        with self.assertRaises(actions.ActionError):
            actions.run_action("mute-audio", platform="linux", runner=runner, which=always_present)

    def test_the_timeout_is_passed_to_the_runner(self):
        # The login signal depends on it: a blocked action thread must not sit
        # on a worker while /ping queues behind it.
        runner = FakeRunner()
        actions.run_action("mute-audio", platform="linux", runner=runner, which=always_present)
        self.assertEqual(runner.calls[0][1], actions.TIMEOUT_S)

    def test_windows_gets_longer_than_two_seconds_because_it_compiles_first(self):
        # `Add-Type` runs the C# compiler on every press and powershell has
        # to start before it. Two seconds means every Windows press is a
        # timeout, which is a 500 on a machine where nothing is wrong.
        self.assertGreater(actions.timeout_for("win32"), actions.TIMEOUT_S)
        self.assertEqual(actions.timeout_for("linux"), actions.TIMEOUT_S)
        self.assertEqual(actions.timeout_for("darwin"), actions.TIMEOUT_S)
        runner = FakeRunner()
        actions.run_action("mute-mic", platform="win32", runner=runner, which=always_present)
        self.assertEqual(runner.calls[0][1], actions.WINDOWS_TIMEOUT_S)


class DescribeTests(unittest.TestCase):
    """The startup line. T8.1 step 4 asks for it by name, and the reason is
    that "nothing happened" is the hardest failure on this project to diagnose
    from the desk."""

    def test_it_names_the_command_that_will_run(self):
        lines = actions.describe(["mute-audio"], platform="linux", which=always_present)
        self.assertEqual(lines, ["  mute-audio: wpctl"])

    def test_it_names_the_fallback_when_the_first_is_missing(self):
        lines = actions.describe(
            ["mute-audio"], platform="linux",
            which=lambda name: "/usr/bin/pactl" if name == "pactl" else None,
        )
        self.assertEqual(lines, ["  mute-audio: pactl"])

    def test_a_box_with_no_mixer_says_so_before_anyone_presses_anything(self):
        line, = actions.describe(["mute-audio"], platform="linux", which=never_present)
        self.assertIn("no command available", line)
        self.assertIn("wpctl", line)
        self.assertIn("501", line)

    def test_a_box_with_only_pipewires_own_tool_cannot_mute_the_microphone(self):
        # T8.3 narrowed `mute-mic` to `pactl`, and this line is where the
        # owner finds that out -- at startup, with a console in front of
        # them, rather than at a press that answers 501.
        line, = actions.describe(
            ["mute-mic"], platform="linux",
            which=lambda name: "/usr/bin/wpctl" if name == "wpctl" else None,
        )
        self.assertIn("no command available", line)
        self.assertIn("pactl", line)
        self.assertIn("501", line)

    def test_an_unknown_platform_says_so_too(self):
        line, = actions.describe(["mute-mic"], platform="aix", which=always_present)
        self.assertIn("nothing", line)

    def test_nothing_enabled_is_no_lines(self):
        self.assertEqual(actions.describe([], platform="linux", which=always_present), [])


class StateTests(unittest.TestCase):
    def test_silence_is_unknown_and_never_a_guess(self):
        # wpctl and pactl print nothing. A button showing a state this server
        # invented is what ADR 0015 forbids.
        self.assertEqual(actions.state_from("mute-audio", "", 0), actions.UNKNOWN)

    def test_a_word_the_command_printed_is_taken_at_its_word(self):
        self.assertEqual(actions.state_from("mute-mic", "muted\n", 0), actions.MUTED)
        self.assertEqual(actions.state_from("mute-mic", "unmuted\n", 0), actions.UNMUTED)

    def test_osascript_booleans_are_translated(self):
        self.assertEqual(actions.state_from("mute-audio", "true", 0), actions.MUTED)
        self.assertEqual(actions.state_from("mute-audio", "false", 0), actions.UNMUTED)

    def test_a_failed_command_reports_no_state_at_all(self):
        self.assertEqual(actions.state_from("mute-audio", "muted", 1), actions.UNKNOWN)

    def test_applescripts_missing_value_is_unknown_and_not_muted(self):
        # `missing value` is AppleScript for "the audio API would not say".
        # Reading it as `muted` is the guess ADR 0015 forbids -- and the
        # direction of the guess is the dangerous one for `mute-mic`.
        self.assertEqual(actions.state_from("mute-mic", "missing value", 0), actions.UNKNOWN)

    def test_the_macos_toggles_both_end_on_a_word(self):
        # An osascript ending on `set volume ...` prints nothing, because the
        # command returns no result -- so the state would always be unknown.
        for action in actions.CATALOGUE:
            argv, = actions.candidates(action, "darwin")
            self.assertIn('return "muted"', argv[-1], action)
            self.assertIn('return "unmuted"', argv[-1], action)


class ReadbackTests(unittest.TestCase):
    """The state is measured, not guessed.

    ADR 0015 said a toggle's state is whatever the command reported, and on
    Linux that is nothing at all -- so the honest answer was `unknown` and the
    panel drew no state. Asked for from the chair: the button carries a cross
    when the PC is muted. A second, read-only command is what makes that
    honest rather than a guess, and these are the tests that keep it honest.
    """

    def test_wpctl_prints_the_flag_only_when_it_is_set(self):
        self.assertEqual(actions.state_from_readback("Volume: 0.40 [MUTED]"), actions.MUTED)
        self.assertEqual(actions.state_from_readback("Volume: 0.40"), actions.UNMUTED)

    def test_pactl_answers_in_words(self):
        self.assertEqual(actions.state_from_readback("Mute: yes"), actions.MUTED)
        self.assertEqual(actions.state_from_readback("Mute: no"), actions.UNMUTED)

    def test_anything_it_does_not_recognise_is_unknown(self):
        # This function is the only thing between a mixer's stdout and a cross
        # drawn over a microphone icon. It guesses nothing.
        for text in ("", None, "garbage", "Volumen: 0.4", "Mute: perhaps", "0.40"):
            self.assertEqual(actions.state_from_readback(text), actions.UNKNOWN, repr(text))

    def test_the_readback_is_read_only(self):
        # A command that could change the mixer would make asking the question
        # change the answer. Asserted by shape, since nothing here runs it.
        # `mute-mic` on Linux has no table entry -- it measures each input
        # inside the press -- and the same property is asserted there.
        for action in actions.CATALOGUE:
            for argv in actions.readback(action, "linux"):
                self.assertTrue(argv[1].startswith("get-"), argv)
                self.assertNotIn("set", argv[1])

    def test_the_default_source_alone_is_no_longer_the_microphones_state(self):
        # Removing this entry is a decision, not an omission: one default
        # source saying `Mute: yes` is not three microphones being off.
        self.assertEqual(actions.readback("mute-mic", "linux"), [])

    def test_a_toggle_that_says_nothing_is_asked(self):
        calls = []

        def runner(argv, timeout):
            calls.append(argv)
            out = "" if argv[1] == "set-mute" else "Volume: 0.40 [MUTED]"
            return subprocess.CompletedProcess(argv, 0, out, "")

        state = actions.run_action("mute-audio", platform="linux",
                                   runner=runner, which=always_present)
        self.assertEqual(state, actions.MUTED)
        self.assertEqual(len(calls), 2, "the mixer was not asked")
        self.assertEqual(calls[1][1], "get-volume")

    def test_a_toggle_that_answers_is_not_asked_twice(self):
        # macOS says the word itself. Asking again would be a second process
        # per press for an answer already in hand.
        runner = FakeRunner(stdout="muted\n")
        state = actions.run_action("mute-audio", platform="darwin",
                                   runner=runner, which=always_present)
        self.assertEqual(state, actions.MUTED)
        self.assertEqual(len(runner.calls), 1)

    def test_a_readback_that_fails_does_not_fail_the_action(self):
        # The toggle already worked and the caller is owed its 200. All the
        # read-back decides is whether a cross is drawn.
        def runner(argv, timeout):
            if argv[1] == "set-mute":
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "no such sink")

        self.assertEqual(
            actions.run_action("mute-audio", platform="linux",
                               runner=runner, which=always_present),
            actions.UNKNOWN)

    def test_a_readback_that_times_out_does_not_raise(self):
        def runner(argv, timeout):
            if argv[1] == "set-mute":
                return subprocess.CompletedProcess(argv, 0, "", "")
            raise subprocess.TimeoutExpired("wpctl", timeout)

        self.assertEqual(
            actions.run_action("mute-audio", platform="linux",
                               runner=runner, which=always_present),
            actions.UNKNOWN)

    def test_a_platform_with_no_readback_stays_unknown(self):
        runner = FakeRunner(stdout="")
        self.assertEqual(actions.readback("mute-audio", "win32"), [])
        self.assertEqual(
            actions.run_action("mute-audio", platform="win32",
                               runner=runner, which=always_present),
            actions.UNKNOWN)


class RunnerEnvironmentTests(unittest.TestCase):
    """The one test that runs a real subprocess, and it is not a mixer one.

    `_default_runner` is the only place this module touches the machine, and
    everything it returns is *parsed* -- `Mute: yes`, `Volume: 0.40 [MUTED]`.
    `pactl` binds the `pulseaudio` text domain, so those words are translated
    on a desktop with language packs installed, and the server inherits the
    graphical session's environment (invariant 2) -- which is the one that
    has a language set. A translated `Mute:` reads as `unknown`, and the
    Linux microphone press refuses to guess a direction from `unknown`, so
    the button would answer 500 on every press in Berlin and work in C.
    """

    def test_the_child_runs_in_the_C_locale(self):
        done = actions._default_runner(
            [sys.executable, "-c", "import os;print(os.environ.get('LC_ALL'))"], 30)
        self.assertEqual(done.stdout.strip(), "C")

    def test_the_rest_of_the_environment_is_still_there(self):
        # A bare `env={"LC_ALL": "C"}` would strip PATH, HOME and the session
        # bus address -- and `pactl` finds the server through the last of
        # those.
        done = actions._default_runner(
            [sys.executable, "-c", "import os;print(len(os.environ))"], 30)
        self.assertGreater(int(done.stdout.strip()), 1)


SOURCES = (
    "54\talsa_output.pci-0000_01_00.1.hdmi-stereo.monitor\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
    "56\talsa_input.usb-0bda_Fosi_Audio_K5_Pro-00.analog-stereo\tPipeWire\ts16le 2ch 48000Hz\tSUSPENDED\n"
    "57\talsa_output.usb-C-Media_MCHOSE_V9_PRO-01.analog-stereo.monitor\tPipeWire\ts24le 2ch 48000Hz\tIDLE\n"
    "58\talsa_input.usb-C-Media_MCHOSE_V9_PRO-01.mono-fallback\tPipeWire\ts24le 1ch 48000Hz\tRUNNING\n"
    "60\talsa_input.pci-0000_11_00.6.analog-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
)

INPUTS = [
    "alsa_input.usb-0bda_Fosi_Audio_K5_Pro-00.analog-stereo",
    "alsa_input.usb-C-Media_MCHOSE_V9_PRO-01.mono-fallback",
    "alsa_input.pci-0000_11_00.6.analog-stereo",
]


class PactlFake:
    """A `pactl` that answers the four questions the Linux mic press asks.

    It keeps the mute flags it is given, so the read-back at the end of a
    press reports what the press actually did rather than a canned word --
    which is the only way a test can tell "muted every input" from "muted the
    first one and said so".
    """

    def __init__(self, sources=SOURCES, muted=(), stuck=(), refuse=(), answers=None):
        self.calls = []
        self.sources = sources
        self.muted = {name: True for name in muted}   # the state it starts in
        self.stuck = set(stuck)      # takes the command, does not move
        self.refuse = set(refuse)    # exits non-zero
        self.answers = answers or {}  # name -> the word `pactl` prints, always

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        verb = argv[1]
        if verb == "list":
            return subprocess.CompletedProcess(argv, 0, self.sources, "")
        if verb == "get-source-mute":
            name = argv[2]
            word = self.answers.get(name, "yes" if self.muted.get(name) else "no")
            return subprocess.CompletedProcess(argv, 0, f"Mute: {word}\n", "")
        if verb == "set-source-mute":
            name, flag = argv[2], argv[3]
            if name in self.refuse:
                return subprocess.CompletedProcess(
                    argv, 1, "", f"Failure: No such entity: {name}\n")
            if name not in self.stuck:
                self.muted[name] = flag == "1"
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"the press ran something it should not: {argv}")

    def verbs(self):
        return [(argv[1], argv[2] if len(argv) > 2 else None) for argv, _ in self.calls]


class CaptureSourcesTests(unittest.TestCase):
    """The names the press is allowed to touch, and the ones it must not."""

    def test_the_monitors_are_skipped_and_the_inputs_are_not(self):
        # A monitor is a loopback of an output. Muting one silences a screen
        # recording and no person at all -- a bug in the opposite direction
        # from the one T8.3 is about.
        self.assertEqual(actions.capture_sources(SOURCES), INPUTS)

    def test_nothing_at_all_is_an_empty_list_and_not_a_crash(self):
        for text in ("", None, "\n", "   \n\n"):
            self.assertEqual(actions.capture_sources(text), [], repr(text))

    def test_a_short_or_broken_line_is_skipped(self):
        self.assertEqual(actions.capture_sources("garbage\n58\talsa_input.x\tPipeWire\n"),
                         ["alsa_input.x"])

    def test_columns_padded_with_spaces_still_read(self):
        # Not every build tabs the columns, and a name has never had a space
        # in it, so the second token is the name either way.
        self.assertEqual(
            actions.capture_sources("58   alsa_input.x   PipeWire   s16le 2ch 48000Hz   IDLE"),
            ["alsa_input.x"])

    def test_a_name_listed_twice_is_muted_once(self):
        self.assertEqual(actions.capture_sources("1\talsa_input.x\n2\talsa_input.x\n"),
                         ["alsa_input.x"])


class LinuxMicTests(unittest.TestCase):
    """Every input, or a loud failure. Never a cross over a live microphone.

    The Windows box grew this behaviour on 2026-09-26 after the first press
    muted the default input while the owner was talking into a headset.
    These are the same properties on Linux (T8.3), where the press is several
    `pactl` commands rather than one PowerShell one.
    """

    def press(self, **kwargs):
        runner = PactlFake(**kwargs)
        state = actions.run_action("mute-mic", platform="linux",
                                   runner=runner, which=always_present)
        return runner, state

    def test_every_input_is_muted_and_no_monitor_is_touched(self):
        runner, state = self.press()
        muted = [argv[2] for argv, _ in runner.calls if argv[1] == "set-source-mute"]
        self.assertEqual(muted, INPUTS)
        self.assertTrue(all(not name.endswith(".monitor") for name in muted), muted)
        self.assertEqual(state, actions.MUTED)

    def test_one_press_is_one_direction_for_all_of_them(self):
        # A per-source toggle would leave a machine where two inputs are
        # muted and one is live in exactly that state, for ever, one press
        # after another.
        runner, state = self.press(muted=INPUTS)
        flags = {argv[3] for argv, _ in runner.calls if argv[1] == "set-source-mute"}
        self.assertEqual(flags, {"0"})
        self.assertEqual(state, actions.UNMUTED)

    def test_only_a_machine_that_is_entirely_muted_gets_unmuted(self):
        # Found by review of PR #39. The first cut read the direction from
        # `@DEFAULT_SOURCE@`, so a muted default beside a live headset --
        # exactly the mixed state this task exists to end -- answered
        # "already muted" and the press **opened every microphone**.
        runner, state = self.press(muted=[INPUTS[0]])
        flags = {argv[3] for argv, _ in runner.calls if argv[1] == "set-source-mute"}
        self.assertEqual(flags, {"1"})
        self.assertEqual(state, actions.MUTED)

    def test_a_default_that_is_a_monitor_does_not_strand_the_button(self):
        # The other half of the same finding: a machine whose default source
        # is a monitor -- a normal thing to set for screen recording -- has a
        # default this press never touches, so a direction read from it never
        # moves and the button mutes for ever and never unmutes. The
        # direction comes from the inputs, and there is no reading of
        # `@DEFAULT_SOURCE@` left to go stale.
        asked = [argv[2] for argv, _ in self.press()[0].calls if argv[1] == "get-source-mute"]
        self.assertNotIn("@DEFAULT_SOURCE@", asked)

    def test_the_direction_is_read_before_anything_is_set(self):
        runner, _ = self.press()
        verbs = [verb for verb, _ in runner.verbs()]
        self.assertEqual(verbs[0], "list")
        self.assertEqual(verbs[1:1 + len(INPUTS)], ["get-source-mute"] * len(INPUTS))
        self.assertEqual(verbs[1 + len(INPUTS)], "set-source-mute")

    def test_the_names_come_from_pactl_and_never_from_anywhere_else(self):
        # ADR 0015's rule, on the one id whose commands are built at run time
        # rather than written in the table: every argument of every command
        # is either a literal or a name this listing printed.
        runner, _ = self.press()
        listed = set(actions.capture_sources(SOURCES))
        for argv, _ in runner.calls:
            self.assertEqual(argv[0], "pactl")
            for word in argv[2:]:
                self.assertTrue(word in listed or word in {"short", "sources", "0", "1"}, word)

    def test_one_input_that_refuses_fails_the_whole_press(self):
        # A partial mute reported as `muted` is the lie this task removes.
        with self.assertRaises(actions.ActionError) as caught:
            self.press(refuse=[INPUTS[1]])
        self.assertIn(INPUTS[1], str(caught.exception))

    def test_muted_only_when_every_input_is(self):
        # One microphone that took the command and did not move, which
        # `pactl` reports without failing: the honest answer is `unknown`,
        # which the page draws as no claim at all.
        runner, state = self.press(stuck=[INPUTS[2]])
        self.assertEqual(state, actions.UNKNOWN)

    def test_a_machine_with_no_microphone_is_a_failure_not_a_state(self):
        with self.assertRaises(actions.ActionError):
            self.press(sources="54\talsa_output.x.monitor\tPipeWire\tIDLE\n")

    def test_a_mixer_nobody_can_parse_mutes_rather_than_opens(self):
        # A translated `pactl` is the real case (`LC_ALL=C` is the fix, and
        # it is one environment variable away from being undone). An input
        # whose state cannot be read is not an input known to be muted, so
        # the press mutes -- the only direction that can be taken without
        # knowing anything for certain.
        runner, _ = self.press(answers={name: "perhaps" for name in INPUTS})
        flags = {argv[3] for argv, _ in runner.calls if argv[1] == "set-source-mute"}
        self.assertEqual(flags, {"1"})

    def test_a_state_that_cannot_be_read_at_all_fails_before_anything_is_set(self):
        # Failing is different from answering `unknown`: this is the mixer
        # refusing the question, and finding that out before changing half
        # the machine is the cheaper failure.
        class Silent(PactlFake):
            def __call__(self, argv, timeout):
                done = super().__call__(argv, timeout)
                if argv[1] == "get-source-mute":
                    return subprocess.CompletedProcess(argv, 1, "", "no such entity")
                return done

        runner = Silent()
        with self.assertRaises(actions.ActionError):
            actions.run_action("mute-mic", platform="linux",
                               runner=runner, which=always_present)
        self.assertEqual([argv[1] for argv, _ in runner.calls], ["list", "get-source-mute"])

    def test_a_read_back_that_fails_does_not_fail_the_press(self):
        # Same bargain as every other read-back: the toggles already
        # happened and the caller is owed its 200.
        class Refusing(PactlFake):
            """Answers the direction and then loses the devices."""

            def __call__(self, argv, timeout):
                done = super().__call__(argv, timeout)
                if argv[1] == "get-source-mute" and self.sets_done():
                    return subprocess.CompletedProcess(argv, 1, "", "gone")
                return done

            def sets_done(self):
                return any(argv[1] == "set-source-mute" for argv, _ in self.calls)

        runner = Refusing()
        self.assertEqual(
            actions.run_action("mute-mic", platform="linux",
                               runner=runner, which=always_present),
            actions.UNKNOWN)
        self.assertEqual(len([1 for argv, _ in runner.calls if argv[1] == "set-source-mute"]),
                         len(INPUTS))

    def test_a_read_back_that_times_out_does_not_raise(self):
        class Hanging(PactlFake):
            def __call__(self, argv, timeout):
                if (argv[1] == "get-source-mute"
                        and any(a[1] == "set-source-mute" for a, _ in self.calls)):
                    raise subprocess.TimeoutExpired("pactl", timeout)
                return super().__call__(argv, timeout)

        self.assertEqual(
            actions.run_action("mute-mic", platform="linux",
                               runner=Hanging(), which=always_present),
            actions.UNKNOWN)

    def test_a_listing_that_times_out_is_an_action_error(self):
        runner = FakeRunner(raises=subprocess.TimeoutExpired("pactl", 2.0))
        with self.assertRaises(actions.ActionError) as caught:
            actions.run_action("mute-mic", platform="linux",
                               runner=runner, which=always_present)
        self.assertIn("did not finish", str(caught.exception))

    def test_every_command_of_the_press_carries_the_platform_timeout(self):
        # Several commands is several chances to sit on a thread. The login
        # signal is what is at stake, so each one is bounded.
        runner, _ = self.press()
        self.assertEqual({timeout for _, timeout in runner.calls}, {actions.TIMEOUT_S})

    def test_the_press_reads_with_get_and_writes_with_set_and_nothing_else(self):
        # The read-only half of the press, asserted the way `_READBACK`'s
        # entries are: a question that could change the mixer would make
        # asking it change the answer.
        runner, _ = self.press()
        for argv, _ in runner.calls:
            self.assertIn(argv[1], {"list", "get-source-mute", "set-source-mute"}, argv)
        after = [verb for verb, _ in runner.verbs()][-len(INPUTS):]
        self.assertEqual(after, ["get-source-mute"] * len(INPUTS))

    def test_a_row_that_only_asks_a_question_must_have_a_press_behind_it(self):
        # Found by review of PR #39. `mute-mic`'s Linux row is a read-only
        # listing, which is safe only because `_SEQUENCES` takes over before
        # it is reached. If the two ever key differently, `run_action` runs
        # the listing **as the action**: exit 0, nothing muted, and a 200 --
        # the "nothing happened" failure the root CLAUDE.md calls the hardest
        # on this project to diagnose.
        for action in actions.CATALOGUE:
            for platform in ("linux", "darwin", "win32"):
                for argv in actions.candidates(action, platform):
                    if argv[0] not in {"pactl", "wpctl"}:
                        continue
                    if argv[1] == "list" or argv[1].startswith("get-"):
                        self.assertIn(platform, actions._SEQUENCES.get(action, {}),
                                      f"{action}/{platform}: it asks, and nothing acts")

    def test_no_pactl_is_unsupported_and_runs_nothing(self):
        # The row in the table is the press's first command, which is also
        # the binary to probe for -- a box with `wpctl` alone answers 501.
        runner = PactlFake()
        with self.assertRaises(actions.Unsupported):
            actions.run_action("mute-mic", platform="linux", runner=runner,
                               which=lambda name: "/usr/bin/wpctl" if name == "wpctl" else None)
        self.assertEqual(runner.calls, [])


class SourceStateTests(unittest.TestCase):
    def test_all_muted_is_muted_and_all_live_is_unmuted(self):
        self.assertEqual(actions.state_from_sources([actions.MUTED] * 3), actions.MUTED)
        self.assertEqual(actions.state_from_sources([actions.UNMUTED] * 3), actions.UNMUTED)

    def test_a_mix_is_unknown_and_never_muted(self):
        # The cross is a claim about every microphone in the machine.
        self.assertEqual(
            actions.state_from_sources([actions.MUTED, actions.UNMUTED]), actions.UNKNOWN)
        self.assertEqual(
            actions.state_from_sources([actions.MUTED, actions.UNKNOWN]), actions.UNKNOWN)

    def test_nothing_measured_is_unknown(self):
        self.assertEqual(actions.state_from_sources([]), actions.UNKNOWN)


class EnabledActionsTests(unittest.TestCase):
    def test_a_list_of_known_names_is_the_enabled_set(self):
        self.assertEqual(actions.enabled_actions(["mute-mic"]), ["mute-mic"])

    def test_missing_and_empty_are_nothing_enabled(self):
        for raw in (None, [], {}):
            self.assertEqual(actions.enabled_actions(raw), [], repr(raw))

    def test_the_reserved_empty_table_still_loads(self):
        # config.example.toml shipped `[actions]` and installed configs have
        # it. An update that refuses to start is worse than a shape change.
        self.assertEqual(actions.enabled_actions({}), [])

    def test_a_non_empty_table_says_what_to_write_instead(self):
        with self.assertRaises(ValueError) as caught:
            actions.enabled_actions({"lock": "shutdown -h now"})
        self.assertIn("list of names", str(caught.exception))

    def test_an_unknown_name_fails_the_load_and_names_itself(self):
        # The point of failing here rather than 404ing later: the owner is at
        # a console when this prints.
        with self.assertRaises(ValueError) as caught:
            actions.enabled_actions(["mute-audio", "mute-evrything"])
        self.assertIn("mute-evrything", str(caught.exception))

    def test_a_command_smuggled_in_as_a_name_is_an_unknown_name(self):
        with self.assertRaises(ValueError):
            actions.enabled_actions(["shutdown -h now"])

    def test_a_non_string_entry_is_rejected(self):
        with self.assertRaises(ValueError):
            actions.enabled_actions([["wpctl", "set-mute"]])

    def test_duplicates_collapse(self):
        self.assertEqual(actions.enabled_actions(["mute-mic", "mute-mic"]), ["mute-mic"])


class StubApp:
    """An App-shaped object for `route`, with the execution counted."""

    def __init__(self, enabled, result=actions.MUTED, raises=None):
        self.enabled_actions = enabled
        self.result = result
        self.raises = raises
        self.ran = []

    def run_action(self, action):
        self.ran.append(action)
        if self.raises is not None:
            raise self.raises
        return self.result


class RouteTests(unittest.TestCase):
    def _json(self, body):
        import json
        return json.loads(body.decode("utf-8"))

    def test_an_enabled_action_runs_and_reports_its_state(self):
        app = StubApp(["mute-audio"])
        status, body, content_type, _ = route("POST", "/action/mute-audio", app)
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(
            self._json(body), {"ok": True, "id": "mute-audio", "state": "muted"}
        )
        self.assertEqual(app.ran, ["mute-audio"])

    def test_an_id_that_is_not_enabled_runs_nothing_at_all(self):
        # The call count is the assertion. A 404 produced *after* spawning
        # something would pass a status-only test and fail the endpoint.
        app = StubApp([])
        status, body, _, _ = route("POST", "/action/mute-audio", app)
        self.assertEqual(status, 404)
        self.assertEqual(app.ran, [])
        self.assertEqual(self._json(body), {"error": "unknown action"})

    def test_an_id_outside_the_catalogue_runs_nothing_at_all(self):
        app = StubApp(["mute-audio"])
        status, _, _, _ = route("POST", "/action/not-an-action", app)
        self.assertEqual(status, 404)
        self.assertEqual(app.ran, [])

    def test_a_disabled_action_is_indistinguishable_from_a_missing_one(self):
        # The endpoint does not tell an unauthenticated caller which actions
        # exist but are switched off.
        app = StubApp([])
        disabled = route("POST", "/action/mute-audio", app)
        missing = route("POST", "/action/not-an-action", app)
        self.assertEqual(disabled[0], missing[0])
        self.assertEqual(disabled[1], missing[1])

    def test_a_path_shaped_id_never_reaches_the_app(self):
        app = StubApp(["mute-audio"])
        status, _, _, _ = route("POST", "/action/../../etc/passwd", app)
        self.assertEqual(status, 404)
        self.assertEqual(app.ran, [])

    def test_an_unsupported_platform_is_501(self):
        app = StubApp(["mute-audio"], raises=actions.Unsupported("no wpctl"))
        status, body, _, _ = route("POST", "/action/mute-audio", app)
        self.assertEqual(status, 501)
        self.assertEqual(self._json(body), {"error": "not implemented on this platform"})

    def test_a_failure_is_500_and_the_stderr_stays_out_of_the_body(self):
        secret = "/home/someone/.config/pulse/cookie is unreadable"
        app = StubApp(["mute-audio"], raises=actions.ActionError(secret))
        status, body, _, _ = route("POST", "/action/mute-audio", app)
        self.assertEqual(status, 500)
        self.assertNotIn(secret.encode(), body)
        self.assertEqual(self._json(body), {"error": "action failed"})

    def test_no_app_is_503_like_every_other_configured_route(self):
        status, body, _, _ = route("POST", "/action/mute-audio", None)
        self.assertEqual(status, 503)
        self.assertEqual(self._json(body), {"error": "not configured"})

    def test_get_never_acts(self):
        # A GET that changes the machine is one browser prefetch away from
        # muting the PC by accident.
        app = StubApp(["mute-audio"])
        status, _, _, _ = route("GET", "/action/mute-audio", app)
        self.assertEqual(status, 404)
        self.assertEqual(app.ran, [])


class BrowserOriginTests(unittest.TestCase):
    """The drive-by a `POST`-only rule does not stop.

    A cross-origin form POST with `enctype=text/plain` is a CORS simple
    request: no preflight, so nothing here gets asked, and the attacker not
    being able to read the response does not matter because the mute already
    happened. Found by review; ADR 0015 was amended rather than left saying
    "as trustworthy as the LAN"."""

    def _run(self, headers, enabled=("mute-audio",)):
        app = StubApp(list(enabled))
        status, body, _, _ = route("POST", "/action/mute-audio", app, headers)
        return status, app.ran

    def test_a_form_post_from_any_page_is_refused_and_runs_nothing(self):
        status, ran = self._run({"Origin": "https://example.invalid"})
        self.assertEqual(status, 403)
        self.assertEqual(ran, [])

    def test_a_same_origin_post_from_a_page_is_refused_too(self):
        # There is no page this server serves that should be posting here --
        # the panel's client is Java. Allowing same-origin would mean trusting
        # an `Origin` an attacker also controls the spelling of.
        status, ran = self._run({"Origin": "http://192.168.1.100:8777"})
        self.assertEqual(status, 403)
        self.assertEqual(ran, [])

    def test_sec_fetch_site_alone_is_enough_to_refuse(self):
        status, ran = self._run({"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertEqual(ran, [])

    def test_the_panels_own_client_sends_neither_and_is_allowed(self):
        # HttpURLConnection, curl and probe.py all send no Origin and no
        # Sec-Fetch-Site. This is the case that must keep working.
        status, ran = self._run({"User-Agent": "Java/21", "Host": "192.168.1.100:8777"})
        self.assertEqual(status, 200)
        self.assertEqual(ran, ["mute-audio"])

    def test_sec_fetch_site_none_is_not_a_browser_page(self):
        # "none" is a user-initiated navigation, not a page making a request.
        status, _ = self._run({"Sec-Fetch-Site": "none"})
        self.assertEqual(status, 200)

    def test_an_empty_origin_header_is_not_an_origin(self):
        status, _ = self._run({"Origin": ""})
        self.assertEqual(status, 200)

    def test_no_headers_at_all_still_routes(self):
        # route() is called with three arguments all over the test suite.
        status, _ = self._run(None)
        self.assertEqual(status, 200)

    def test_the_allowlist_is_still_checked_first(self):
        # An unknown id is 404 whether or not a browser sent it: it does
        # nothing either way, and T8.1's acceptance asserts that status.
        app = StubApp(["mute-audio"])
        status, _, _, _ = route(
            "POST", "/action/not-an-action", app, {"Origin": "https://example.invalid"}
        )
        self.assertEqual(status, 404)
        self.assertEqual(app.ran, [])


class PayloadTests(unittest.TestCase):
    """Which buttons exist is config, not code (T8.2 step 4)."""

    def _payload(self, config):
        app = App(dict({"quotes": [], "fx": [], "crypto": []}, **config))
        return app.quotes()

    def test_the_enabled_ids_ride_the_payload(self):
        self.assertEqual(self._payload({"actions": ["mute-mic"]})["actions"], ["mute-mic"])

    def test_nothing_enabled_is_an_empty_list_and_not_a_missing_key(self):
        # A missing key and an empty list are different things to the page:
        # one is "no buttons", the other is "an older server that cannot tell
        # you". The key is always present.
        payload = self._payload({})
        self.assertIn("actions", payload)
        self.assertEqual(payload["actions"], [])

    def test_the_catalogue_is_not_what_is_sent(self):
        # The panel must never draw a button for an action the server would
        # answer 404 to -- a button that does nothing is worse than no button
        # (T8.2 step 7). So this is the *enabled* set, not actions.CATALOGUE.
        payload = self._payload({"actions": ["mute-audio"]})
        self.assertEqual(payload["actions"], ["mute-audio"])
        self.assertNotIn("mute-mic", payload["actions"])

    def test_the_page_cannot_mutate_the_app_through_the_payload(self):
        # A copy, not the App's own list: the payload is serialised straight
        # to JSON today and handing out the live allowlist is the kind of
        # aliasing that costs nothing until something edits it.
        app = App({"quotes": [], "fx": [], "crypto": [], "actions": ["mute-mic"]})
        app.quotes()["actions"].append("shutdown")
        self.assertEqual(app.enabled_actions, ["mute-mic"])


class AppWiringTests(unittest.TestCase):
    def test_an_app_validates_its_actions_when_it_is_built(self):
        with self.assertRaises(ValueError):
            App({"actions": ["mute-evrything"]})

    def test_an_app_with_no_actions_key_enables_nothing(self):
        self.assertEqual(App({}).enabled_actions, [])

    def test_an_app_carries_the_enabled_names(self):
        self.assertEqual(App({"actions": ["mute-mic"]}).enabled_actions, ["mute-mic"])


if __name__ == "__main__":
    unittest.main()
