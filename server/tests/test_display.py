"""T4.6: whether this session's display is on, and what /ping says about it.

No display is touched and nothing is forked: the decoders are pure, the Linux
reader takes its `run` and `which`, and the Windows message is a struct built
in memory. What only a real desktop can show -- the event arriving on Windows,
Mutter's answer on a GNOME box -- is the task file's manual check.
"""
import ctypes
import json
import unittest

from server import display
from server.server import App, DEFAULT_CONFIG, route


def _config(**overrides):
    config = dict(DEFAULT_CONFIG)
    config.update(overrides)
    return config


class DecoderTests(unittest.TestCase):
    def test_windows_payload(self):
        self.assertEqual(display.windows_state(0), display.OFF)
        self.assertEqual(display.windows_state(1), display.ON)
        # Dimmed is on: the owner can still read it.
        self.assertEqual(display.windows_state(2), display.ON)
        self.assertEqual(display.windows_state(7), display.UNKNOWN)

    def test_mutter_power_save_mode(self):
        self.assertEqual(display.mutter_state("(<0>,)\n"), display.ON)
        for mode in (1, 2, 3):
            self.assertEqual(display.mutter_state(f"(<{mode}>,)\n"), display.OFF)
        self.assertEqual(display.mutter_state("(<-1>,)\n"), display.UNKNOWN)
        self.assertEqual(display.mutter_state("(<int32 0>,)\n"), display.ON)
        self.assertEqual(display.mutter_state(""), display.UNKNOWN)

    def test_xset_dpms_line(self):
        on = "DPMS (Energy Star):\n  Standby: 600\n  DPMS is Enabled\n  Monitor is On\n"
        self.assertEqual(display.xset_state(on), display.ON)
        for level in ("Off", "in Standby", "in Suspend"):
            self.assertEqual(display.xset_state(f"  Monitor is {level}\n"), display.OFF)
        self.assertEqual(display.xset_state("DPMS (Energy Star):\n  Server does not have "
                                            "the DPMS Extension\n"), display.UNKNOWN)

    def test_macos_needs_every_display_asleep(self):
        self.assertEqual(display.macos_state([True, True]), display.OFF)
        self.assertEqual(display.macos_state([True, False]), display.ON)
        self.assertEqual(display.macos_state([]), display.UNKNOWN)


class LinuxReaderTests(unittest.TestCase):
    def test_mutter_answers_first(self):
        calls = []

        def run(argv):
            calls.append(argv[0])
            return "(<3>,)\n"

        self.assertEqual(display.read_linux(run=run, which=lambda _: True), display.OFF)
        self.assertEqual(calls, ["gdbus"])

    def test_falls_back_to_xset_when_mutter_is_not_there(self):
        def run(argv):
            return None if argv[0] == "gdbus" else "  Monitor is On\n"

        self.assertEqual(display.read_linux(run=run, which=lambda _: True), display.ON)

    def test_nothing_installed_is_unknown(self):
        self.assertEqual(display.read_linux(run=lambda argv: self.fail(argv),
                                            which=lambda _: None), display.UNKNOWN)


class SampledTests(unittest.TestCase):
    def test_answers_the_last_reading_without_reading(self):
        readings = iter([display.OFF, display.ON])
        sampled = display.Sampled(lambda: next(readings), start=False)
        self.assertEqual(sampled.state(), display.UNKNOWN)
        sampled.sample()
        self.assertEqual(sampled.state(), display.OFF)
        self.assertEqual(sampled.state(), display.OFF)
        sampled.sample()
        self.assertEqual(sampled.state(), display.ON)

    def test_a_reader_that_raises_is_unknown(self):
        def broken():
            raise OSError("no bus")

        sampled = display.Sampled(broken, start=False)
        self.assertEqual(sampled.sample(), display.UNKNOWN)


class WindowsMessageTests(unittest.TestCase):
    """The window procedure's decoding, fed a POWERBROADCAST_SETTING built here.

    The watcher itself is constructed without its thread: `__new__` plus the
    two fields `on_message` touches, because the real constructor opens a
    window and that needs Windows.
    """

    def _watcher(self):
        watcher = display.WindowsWatcher.__new__(display.WindowsWatcher)
        watcher._value = display.UNKNOWN
        watcher._ready = __import__("threading").Event()
        return watcher

    def _setting(self, guid, value):
        setting = display.PowerBroadcastSetting()
        setting.PowerSetting = display.Guid.parse(guid)
        setting.DataLength = 4
        setting.Data[0] = value
        return setting

    def test_guid_round_trips(self):
        text = display.GUID_CONSOLE_DISPLAY_STATE
        self.assertEqual(str(display.Guid.parse(text)), text)

    def test_display_off_then_on(self):
        watcher = self._watcher()
        off = self._setting(display.GUID_CONSOLE_DISPLAY_STATE, 0)
        self.assertTrue(watcher.on_message(display.WM_POWERBROADCAST,
                                           display.PBT_POWERSETTINGCHANGE,
                                           ctypes.addressof(off)))
        self.assertEqual(watcher.state(), display.OFF)
        self.assertTrue(watcher._ready.is_set())
        on = self._setting(display.GUID_CONSOLE_DISPLAY_STATE, 1)
        watcher.on_message(display.WM_POWERBROADCAST, display.PBT_POWERSETTINGCHANGE,
                           ctypes.addressof(on))
        self.assertEqual(watcher.state(), display.ON)

    def test_other_settings_and_messages_are_ignored(self):
        watcher = self._watcher()
        other = self._setting("02731015-4510-4526-99e6-e5a17ebd1aea", 0)  # away mode
        self.assertFalse(watcher.on_message(display.WM_POWERBROADCAST,
                                            display.PBT_POWERSETTINGCHANGE,
                                            ctypes.addressof(other)))
        self.assertFalse(watcher.on_message(0x0010, 0, 0))
        self.assertFalse(watcher.on_message(display.WM_POWERBROADCAST,
                                            display.PBT_POWERSETTINGCHANGE, 0))
        self.assertEqual(watcher.state(), display.UNKNOWN)


class WatcherChoiceTests(unittest.TestCase):
    def test_off_in_config_is_always_unknown(self):
        reader = display.watcher({"follow_display": False}, platform="darwin")
        self.assertIsInstance(reader, display.Fixed)
        self.assertEqual(reader.state(), display.UNKNOWN)

    def test_a_platform_with_no_reader_is_unknown(self):
        self.assertEqual(display.watcher({}, platform="freebsd14").state(), display.UNKNOWN)

    def test_the_default_is_on(self):
        self.assertIs(DEFAULT_CONFIG["follow_display"], True)


class PingCarriesTheDisplayTests(unittest.TestCase):
    def _ping(self, app):
        status, body, _, _ = route("GET", "/ping", app)
        self.assertEqual(status, 200)
        return json.loads(body.decode("utf-8"))

    def test_an_app_reports_its_display(self):
        app = App(_config(), display=display.Fixed(display.OFF))
        self.assertEqual(self._ping(app), {"ok": True, "display": "off"})

    def test_an_app_without_a_reader_says_unknown(self):
        self.assertEqual(self._ping(App(_config())), {"ok": True, "display": "unknown"})

    def test_no_app_is_the_old_body(self):
        self.assertEqual(self._ping(None), {"ok": True})


if __name__ == "__main__":
    unittest.main()
