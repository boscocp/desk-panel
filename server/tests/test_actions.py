"""The one route that changes the machine the server runs on.

[ADR 0015](../../docs/adr/0015-the-panel-can-act-on-the-pc.md) is what these
assert. Nothing here executes a mixer command: the runner is injected, and
several of these tests are about the runner **not** being called at all, which
is why they assert on a call count rather than only on a status code. A test
that only checks the response cannot tell 404-after-spawning from
404-before-spawning, and the difference is the whole endpoint.
"""
import subprocess
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
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0][0], "pactl")

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
        actions.run_action("mute-mic", platform="linux", runner=runner, which=always_present)
        self.assertEqual(runner.calls[0][1], actions.TIMEOUT_S)


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
        line, = actions.describe(["mute-mic"], platform="linux", which=never_present)
        self.assertIn("no command available", line)
        self.assertIn("wpctl", line)
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
