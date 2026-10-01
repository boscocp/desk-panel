"""T8.6: the volume rides the spectrum stream.

What is pinned: a helper's `v=` stderr line is parsed strictly and nothing
else is taken for one, the helper's other stderr lines reach the log, the hub
writes a volume line on opening and on each change and never when the volume
action is off, and the App keeps /quotes on the same number in both
directions -- a level heard by the hub, and a level set from the phone.
"""
import io
import threading
import time
import unittest
from unittest import mock

from server import actions, spectrum
from server.server import DEFAULT_CONFIG, App


class ParseTests(unittest.TestCase):
    def test_a_volume_line(self):
        self.assertEqual(spectrum.read_volume("v=0"), 0)
        self.assertEqual(spectrum.read_volume("v=51\r"), 51)
        self.assertEqual(spectrum.read_volume("v=100"), 100)

    def test_anything_else_is_not_a_volume(self):
        for text in ("", "v=", "v=101", "v=-1", "v=5.5", "v=0051", "v= 5", "V=5",
                     "v=٥", "spectrum-tap: Start failed", "rate=24000"):
            self.assertIsNone(spectrum.read_volume(text), text)

    def test_the_wire_line(self):
        self.assertEqual(spectrum.volume_line(51), b"v=51\n")
        # Never confused with a frame: the phone tells them apart by shape.
        self.assertNotEqual(len(spectrum.volume_line(100)), spectrum.BARS * 2 + 1)


class _Process:
    def __init__(self, stdout, stderr):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.stdin = mock.Mock()

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class HelperStderrTests(unittest.TestCase):
    def _open(self, stderr):
        process = _Process(b"rate=24000\n", stderr)
        source = spectrum.HelperSource(["tap"], popen=lambda *a, **k: process)
        levels, logged = [], []
        source.watch_stderr(levels.append, logged.append)
        source.open()
        deadline = time.monotonic() + 2
        while process.stderr.tell() < len(stderr) and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        source.close()
        return levels, logged

    def test_volume_lines_go_to_the_hub_and_the_rest_to_the_log(self):
        levels, logged = self._open(
            b"v=40\nv=41\r\nspectrum-tap: GetBuffer failed: 0x88890004\nv=999\n")
        self.assertEqual(levels, [40, 41])
        self.assertEqual(len(logged), 2)
        self.assertIn("GetBuffer failed", logged[0])
        self.assertIn("v=999", logged[1])

    def test_stderr_is_piped(self):
        calls = []

        def popen(argv, **kwargs):
            calls.append(kwargs)
            return _Process(b"rate=24000\n", b"")

        spectrum.HelperSource(["tap"], popen=popen).open()
        self.assertEqual(calls[0]["stderr"], spectrum.subprocess.PIPE)


class HubVolumeTests(unittest.TestCase):
    def _hub(self, owner):
        hub = spectrum.Spectrum(lambda: None, log=lambda m: None)
        hub._running = True  # no capture thread: published by hand
        hub.on_volume = owner
        return hub

    def _next(self, frames, timeout=2):
        out = []
        reader = threading.Thread(target=lambda: out.append(next(frames)), daemon=True)
        reader.start()
        reader.join(timeout)
        return out[0] if out else None

    def test_a_change_is_a_line_and_the_owner_hears_it(self):
        heard = []
        hub = self._hub(heard.append)
        frames = hub.frames()
        self.assertEqual(next(frames), spectrum.SILENT_FRAME)
        hub.note_volume(51)
        self.assertEqual(self._next(frames), b"v=51\n")
        self.assertEqual(heard, [51])
        frames.close()

    def test_the_same_level_again_is_not_sent(self):
        heard = []
        hub = self._hub(heard.append)
        hub.note_volume(51)
        hub.note_volume(51)
        self.assertEqual(heard, [51])
        self.assertEqual(hub._volume_sequence, 1)

    def test_a_new_stream_starts_with_the_known_level(self):
        hub = self._hub(lambda level: None)
        hub.note_volume(30)
        frames = hub.frames()
        self.assertEqual(next(frames), b"v=30\n")
        self.assertEqual(next(frames), spectrum.SILENT_FRAME)
        frames.close()

    def test_no_owner_means_no_volume_lines(self):
        hub = self._hub(None)
        hub.note_volume(30)
        frames = hub.frames()
        self.assertEqual(next(frames), spectrum.SILENT_FRAME)
        self.assertIsNone(hub._volume)
        frames.close()

    def test_an_unknown_level_is_dropped(self):
        heard = []
        hub = self._hub(heard.append)
        hub.note_volume(None)
        self.assertEqual(heard, [])

    def test_the_level_is_forgotten_when_the_source_closes(self):
        # A helper that has gone says nothing about the knob now (found by
        # review): the next stream must not open with its last word.
        class Source:
            def watch_stderr(self, on_volume, log):
                self.on_volume = on_volume

            def open(self):
                self.on_volume(30)
                return 24000, lambda n: b""

            def close(self):
                pass

        hub = spectrum.Spectrum(Source, log=lambda m: None)
        hub.on_volume = lambda level: None
        with mock.patch.object(spectrum, "RESTART_S", 5.0):
            frames = hub.frames()
            deadline = time.monotonic() + 2
            while hub._volume_sequence < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNone(hub._volume)
            frames.close()

    def test_the_owner_hears_levels_in_the_order_the_hub_kept_them(self):
        heard = []
        hub = self._hub(heard.append)

        def note_many(start):
            for level in range(start, start + 50):
                hub.note_volume(level % 101)

        threads = [threading.Thread(target=note_many, args=(n * 7,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(heard[-1], hub._volume)

    def test_the_hub_hands_its_callbacks_to_the_source(self):
        watched = []

        class Source:
            def watch_stderr(self, on_volume, log):
                watched.append(on_volume)

            def open(self):
                raise OSError("no device")

            def close(self):
                pass

        hub = spectrum.Spectrum(Source, log=lambda m: None)
        with mock.patch.object(spectrum, "RESTART_S", 0.01):
            frames = hub.frames()
            next(frames)
            deadline = time.monotonic() + 2
            while not watched and time.monotonic() < deadline:
                time.sleep(0.01)
            frames.close()
        self.assertEqual(watched[0], hub.note_volume)


class AppTests(unittest.TestCase):
    def _hub(self, reports_volume=True):
        hub = spectrum.Spectrum(lambda: None, log=lambda m: None,
                                reports_volume=reports_volume)
        hub._running = True
        return hub

    def test_a_source_that_reports_no_volume_is_not_wired(self):
        # macOS and Linux: a hub that heard only the phone's sets would open
        # every new stream with the last one (found by review).
        hub = self._hub(reports_volume=False)
        app = App(dict(DEFAULT_CONFIG, actions=["volume"]), spectrum=hub)
        self.assertIsNone(hub.on_volume)
        with mock.patch.object(actions, "set_volume", lambda level: level):
            app.set_volume(30)
        frames = hub.frames()
        self.assertEqual(next(frames), spectrum.SILENT_FRAME)
        frames.close()

    def test_the_hub_feeds_quotes_when_the_volume_action_is_on(self):
        hub = self._hub()
        app = App(dict(DEFAULT_CONFIG, actions=["volume"]), spectrum=hub)
        self.assertEqual(hub.on_volume, app.note_volume)
        with mock.patch.object(actions, "read_volume", lambda: self.fail("read")):
            hub.note_volume(42)
            self.assertEqual(app.volume_level(), 42)

    def test_the_hub_says_nothing_when_the_volume_action_is_off(self):
        hub = self._hub()
        App(dict(DEFAULT_CONFIG, actions=["mute-audio"]), spectrum=hub)
        self.assertIsNone(hub.on_volume)

    def test_a_set_from_the_phone_reaches_every_stream(self):
        hub = self._hub()
        app = App(dict(DEFAULT_CONFIG, actions=["volume"]), spectrum=hub)
        frames = hub.frames()
        next(frames)
        with mock.patch.object(actions, "set_volume", lambda level: level):
            self.assertEqual(app.set_volume(20), 20)
        self.assertEqual(next(frames), b"v=20\n")
        self.assertEqual(app._volume_level, 20)
        frames.close()

    def test_a_set_with_no_hub_still_works(self):
        app = App(dict(DEFAULT_CONFIG, actions=["volume"]))
        with mock.patch.object(actions, "set_volume", lambda level: level):
            self.assertEqual(app.set_volume(70), 70)
        self.assertEqual(app._volume_level, 70)


if __name__ == "__main__":
    unittest.main()
