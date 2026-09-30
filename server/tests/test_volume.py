"""T8.4: the volume bar -- the one action with a value (ADR 0015, third amendment).

What is pinned: the level is an int 0..100 before anything runs, it reaches a
command only as this module formats it, the route keeps run_action's order of
checks, and the private mode's key covers the new path shape.
"""
import json
import subprocess
import unittest

from server import actions
from server.server import DEFAULT_CONFIG, route, volume_level_in

HOST = {"Host": "192.168.1.100:8777"}


class _App:
    def __init__(self, enabled=("volume",), measured=37, raises=None, **config):
        self.enabled_actions = list(enabled)
        self.config = dict(DEFAULT_CONFIG, **config)
        self.levels = []
        self.measured = measured
        self.raises = raises

    def set_volume(self, level):
        if self.raises:
            raise self.raises
        self.levels.append(level)
        return self.measured


def _post(path, app, headers=None, channel="plain"):
    status, body, _, _ = route("POST", path, app, dict(HOST, **(headers or {})), channel)
    return status, json.loads(body) if body else None


class ParseTests(unittest.TestCase):
    def test_only_ascii_digits_zero_to_a_hundred(self):
        good = {"0": 0, "7": 7, "42": 42, "100": 100}
        for text, level in good.items():
            self.assertEqual(actions.parse_level(text), level)
        for text in ("101", "-1", "4a", "0042", "", " 4", "4 ", "4.5", "٣", "1e2", None):
            self.assertIsNone(actions.parse_level(text), repr(text))

    def test_the_path_shape(self):
        self.assertEqual(volume_level_in("/action/volume/42"), 42)
        for path in ("/action/volume", "/action/volume/", "/action/volume/42/x",
                     "/action/volume/101", "/action/volume/..%2f", "/action/mute-mic"):
            self.assertIsNone(volume_level_in(path), path)


class MixerTests(unittest.TestCase):
    def test_every_spelling_a_mixer_reports(self):
        cases = {
            "Volume: 0.42": 42, "Volume: 0.42 [MUTED]": 42, "Volume: 1.30": 100,
            "Volume: front-left: 27525 /  42% / -22.6 dB,   front-right: 27525 /  42%": 42,
            "42": 42, "0": 0, "missing value": None, "": None, None: None,
        }
        for stdout, level in cases.items():
            self.assertEqual(actions.level_from(stdout), level, repr(stdout))

    def test_the_level_reaches_the_command_as_this_module_formats_it(self):
        (w_set, _), (p_set, _) = actions.volume_commands(42, "linux")
        self.assertEqual(w_set[-1], "0.42")
        self.assertEqual(p_set[-1], "42%")
        (_, mac), = actions.volume_commands(7, "darwin")
        self.assertIn("set volume output volume 7\n", mac[-1])
        (_, win), = actions.volume_commands(100, "win32")
        self.assertIn("SetMasterVolumeLevelScalar(1.00f", win[-1])
        with self.assertRaises(ValueError):
            actions.volume_commands(101, "linux")

    def test_a_read_sets_nothing(self):
        for platform in ("linux", "darwin", "win32"):
            for setter, reader in actions.volume_commands(None, platform):
                self.assertIsNone(setter)
                self.assertNotIn("set volume", " ".join(reader))
                self.assertNotIn("SetMasterVolumeLevelScalar(", reader[-1].split("interface")[-1]
                                 if platform == "win32" else "")

    def test_windows_keeps_the_vtable_slots(self):
        (_, win), = actions.volume_commands(None, "win32")
        body = win[-1].split("interface IAudioEndpointVolume {")[1].split("}")[0]
        methods = [line.strip() for line in body.split(";") if line.strip()]
        self.assertEqual(methods.index("int SetMasterVolumeLevelScalar(float level,System.IntPtr c)"), 4)
        self.assertEqual(methods.index("int GetMasterVolumeLevelScalar(out float level)"), 6)

    def test_set_runs_the_setter_then_reads(self):
        ran = []

        def runner(argv, timeout):
            ran.append(argv)
            return subprocess.CompletedProcess(argv, 0, "Volume: 0.40\n", "")

        level = actions.set_volume(40, "linux", runner=runner, which=lambda c: c == "wpctl")
        self.assertEqual(level, 40)
        self.assertEqual([argv[1] for argv in ran], ["set-volume", "get-volume"])

    def test_no_mixer_is_unsupported_and_a_read_is_just_none(self):
        with self.assertRaises(actions.Unsupported):
            actions.set_volume(40, "linux", which=lambda c: None)
        self.assertIsNone(actions.read_volume("linux", which=lambda c: None))

    def test_run_action_refuses_the_volume_without_a_level(self):
        with self.assertRaises(actions.ActionError):
            actions.run_action("volume", "linux")


class RouteTests(unittest.TestCase):
    def test_an_enabled_volume_is_set_and_reports_the_measured_level(self):
        app = _App()
        self.assertEqual(_post("/action/volume/40", app),
                         (200, {"ok": True, "id": "volume", "state": "37"}))
        self.assertEqual(app.levels, [40])

    def test_not_enabled_is_404_and_runs_nothing(self):
        app = _App(enabled=("mute-audio",))
        self.assertEqual(_post("/action/volume/40", app)[0], 404)
        self.assertEqual(app.levels, [])

    def test_a_bad_level_is_404_and_runs_nothing(self):
        app = _App()
        for path in ("/action/volume/101", "/action/volume/-1", "/action/volume/4a",
                     "/action/volume"):
            self.assertEqual(_post(path, app)[0], 404, path)
        self.assertEqual(app.levels, [])

    def test_a_browser_is_refused(self):
        app = _App()
        self.assertEqual(_post("/action/volume/40", app, {"Origin": "http://evil"})[0], 403)
        self.assertEqual(app.levels, [])

    def test_failures_map_like_the_buttons(self):
        self.assertEqual(_post("/action/volume/1", _App(raises=actions.Unsupported("x")))[0], 501)
        self.assertEqual(_post("/action/volume/1", _App(raises=actions.ActionError("x")))[0], 500)
        self.assertEqual(_post("/action/volume/1", _App(measured=None))[1]["state"], "unknown")

    def test_private_mode_needs_the_key_on_this_path_too(self):
        key = "k" * 43
        app = _App(panel_key=key, tls_cert="c.pem", tls_key="k.pem")
        self.assertEqual(_post("/action/volume/40", app, channel="tls")[0], 401)
        self.assertEqual(_post("/action/volume/40", app, {"X-Panel-Key": key}, "tls")[0], 200)
        self.assertEqual(app.levels, [40])


if __name__ == "__main__":
    unittest.main()
