"""T8.7: the Linux source reports the volume too.

What is pinned: which `pactl subscribe` lines count as an output-volume
change and which near-misses do not, which platforms claim to report a level
at all, that the Linux factory builds the source that does it, and that
`ParecSource` reads once on opening, once per sink event, never when the hub
wants no level, and leaves the bars working when `pactl` is missing.
"""
import io
import threading
import time
import unittest
from unittest import mock

from server import spectrum


class SinkEventTests(unittest.TestCase):
    def test_a_sink_change_counts(self):
        self.assertTrue(spectrum.is_sink_event("Event 'change' on sink #57"))
        self.assertTrue(spectrum.is_sink_event("Event 'change' on sink #57\n"))

    def test_a_stream_of_its_own_does_not(self):
        # The one that would make a video's slider redraw the panel's bar.
        self.assertFalse(spectrum.is_sink_event("Event 'change' on sink-input #429"))
        self.assertFalse(spectrum.is_sink_event("Event 'new' on sink-input #429"))

    def test_a_microphone_does_not(self):
        self.assertFalse(spectrum.is_sink_event("Event 'change' on source #3"))
        self.assertFalse(spectrum.is_sink_event("Event 'change' on source-output #8"))

    def test_the_default_sink_changing_counts(self):
        # The real shape: `pactl`'s one format string is `Event '%s' on %s #%u`
        # and the index is always printed, so a server event arrives with the
        # unsigned -1 and never bare. The bare form is tolerated, not expected.
        self.assertTrue(spectrum.is_sink_event("Event 'change' on server #4294967295"))
        self.assertTrue(spectrum.is_sink_event("Event 'change' on server"))

    def test_anything_else_is_not_an_event(self):
        for line in ("", "   ", "Got SIGINT, exiting.", "sink #57",
                     "Connection failure: Connection refused"):
            self.assertFalse(spectrum.is_sink_event(line), line)


class ReportsVolumeTests(unittest.TestCase):
    def test_windows_reads_it_in_the_helper(self):
        self.assertTrue(spectrum.reports_volume("win32", which=lambda name: None))

    def test_linux_needs_pactl(self):
        self.assertTrue(spectrum.reports_volume("linux", which=lambda name: "/usr/bin/pactl"))
        self.assertFalse(spectrum.reports_volume("linux", which=lambda name: None))

    def test_macos_reads_it_in_the_helper(self):
        self.assertTrue(spectrum.reports_volume("darwin", which=lambda name: None))


class SourceForTests(unittest.TestCase):
    def test_linux_builds_the_source_that_watches_the_volume(self):
        factory, reason = spectrum.source_for("linux", which=lambda name: "/usr/bin/" + name)
        self.assertIsNone(reason)
        self.assertIsInstance(factory(), spectrum.ParecSource)


class _Capture:
    """The `parec` half: a rate the source already knows, and no stderr."""

    def __init__(self):
        self.stdout = io.BytesIO(b"\0" * 64)
        self.stderr = io.BytesIO(b"")
        self.stdin = mock.Mock()

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class _Events:
    """The `pactl subscribe` half."""

    def __init__(self, lines, complaint=b""):
        self.stdout = io.BytesIO(lines)
        self.stderr = io.BytesIO(complaint)
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class ParecSourceTests(unittest.TestCase):
    def _open(self, lines, levels=(40,), on_volume=True, which=lambda name: "/usr/bin/" + name,
              complaint=b"", keep=None):
        started, logged = [], []
        events = _Events(lines, complaint)
        readings = list(levels)

        def popen(argv, **kwargs):
            started.append(argv)
            if keep is not None:
                keep[argv[0]] = kwargs
            return events if argv[0] == spectrum.PACTL else _Capture()

        heard = []
        source = spectrum.ParecSource(["parec"], rate=24000, popen=popen, which=which,
                                      read_level=lambda: readings.pop(0) if readings else None)
        if on_volume:
            source.watch_stderr(heard.append, logged.append)
        else:
            source.watch_stderr(None, logged.append)
        source.open()
        deadline = time.monotonic() + 2
        while events.stdout.tell() < len(lines) and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.05)
        source.close()
        return heard, logged, started, events

    def test_the_level_is_read_on_opening(self):
        heard, _, started, _ = self._open(b"", levels=(40,))
        self.assertEqual(heard, [40])
        self.assertIn([spectrum.PACTL, "subscribe"], started)

    def test_one_read_per_sink_event_and_none_for_the_rest(self):
        heard, _, _, _ = self._open(
            b"Event 'change' on sink-input #429\n"
            b"Event 'change' on sink #57\n"
            b"Event 'change' on source #3\n"
            b"Event 'change' on sink #57\n",
            levels=(40, 55, 70))
        # One on opening, then one for each of the two sink lines; the
        # sink-input and the source are not volume the bar shows.
        self.assertEqual(heard, [40, 55, 70])

    def test_a_level_that_does_not_read_is_passed_on_as_none(self):
        # `Spectrum.note_volume` is what drops it, in one place, rather than
        # each source deciding; this only proves the source does not crash.
        heard, _, _, _ = self._open(b"Event 'change' on sink #57\n", levels=())
        self.assertEqual(heard, [None, None])

    def test_no_owner_means_pactl_is_never_started(self):
        heard, _, started, _ = self._open(b"Event 'change' on sink #57\n", on_volume=False)
        self.assertEqual(heard, [])
        self.assertEqual(started, [["parec"]])

    def test_no_pactl_leaves_the_bars_working_and_says_why(self):
        heard, logged, started, _ = self._open(
            b"", which=lambda name: None if name == spectrum.PACTL else "/usr/bin/" + name)
        self.assertEqual(heard, [])
        self.assertEqual(started, [["parec"]])
        self.assertTrue(any("follows /quotes" in line for line in logged), logged)

    def test_closing_ends_the_watch(self):
        _, _, _, events = self._open(b"")
        self.assertTrue(events.terminated)

    def test_the_watch_runs_under_the_c_locale(self):
        # `pactl` translates `Event 'change' on sink #N` wherever the
        # pulseaudio language pack is installed, and the server inherits the
        # graphical session's language (invariant 2). Without this every
        # event stops matching and the bar silently stops following the knob.
        keep = {}
        self._open(b"", keep=keep)
        self.assertEqual(keep[spectrum.PACTL]["env"]["LC_ALL"], "C")

    def test_a_watch_that_dies_on_its_own_says_so(self):
        # `pactl` on PATH but no sound server to reach: it exits at once, and
        # the bar drops back to /quotes. That must not be silent.
        _, logged, _, _ = self._open(
            b"", complaint=b"Connection failure: Connection refused\n")
        self.assertTrue(any("the volume watch ended" in line for line in logged), logged)
        self.assertTrue(any("Connection refused" in line for line in logged), logged)

    def test_a_level_still_in_flight_at_close_is_dropped(self):
        # The read spawns `wpctl` and can outlive close(). The hub forgets a
        # gone source's level on purpose; a late answer must not restore it.
        heard, logged = [], []
        released = threading.Event()
        events = _Events(b"")

        def slow_read():
            released.wait(2)
            return 70

        source = spectrum.ParecSource(
            ["parec"], rate=24000, which=lambda name: "/usr/bin/" + name,
            popen=lambda argv, **kw: events if argv[0] == spectrum.PACTL else _Capture(),
            read_level=slow_read)
        source.watch_stderr(heard.append, logged.append)
        source.open()
        source.close()        # while the read is still blocked
        released.set()
        time.sleep(0.1)
        self.assertEqual(heard, [])


if __name__ == "__main__":
    unittest.main()
