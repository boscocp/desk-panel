"""T8.5: the spectrum bars (ADR 0021).

What is pinned: the FFT and the band layout are right, a known tone lands in
the bar it belongs to at the level its amplitude says, the helper protocol is
parsed and refused when it is not spoken, the hub runs a source only while
somebody watches, and `/spectrum` is a data route that streams over a real
socket and needs the key like the others.
"""
import cmath
import http.client
import io
import json
import math
import random
import threading
import time
import types
import unittest
from functools import partial
from unittest import mock

from server import spectrum
from server.server import DEFAULT_CONFIG, Handler, Server, route

HOST = {"Host": "192.168.1.100:8777"}
RATE = 24000


def tone(hz, amplitude=1.0, rate=RATE, n=spectrum.WINDOW):
    return [amplitude * math.sin(2 * math.pi * hz * i / rate) for i in range(n)]


def bar_for(hz, rate=RATE):
    """The bar whose bins contain `hz`."""
    k = hz / (rate / spectrum.WINDOW)
    for i, (lo, hi) in enumerate(spectrum.band_edges(rate)):
        if lo <= round(k) < hi:
            return i
    raise AssertionError(f"{hz} Hz is in no bar")


class FftTests(unittest.TestCase):
    def test_matches_a_naive_dft(self):
        rng = random.Random(8)
        n = 64
        xs = [complex(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(n)]
        want = [sum(x * cmath.exp(-2j * math.pi * k * t / n) for t, x in enumerate(xs))
                for k in range(n)]
        re, im = [x.real for x in xs], [x.imag for x in xs]
        spectrum.fft(re, im)
        for k in range(n):
            self.assertAlmostEqual(complex(re[k], im[k]), want[k], places=9)


class BandTests(unittest.TestCase):
    def test_contiguous_non_empty_and_inside_nyquist(self):
        for rate in (22050, 24000, 48000):
            edges = spectrum.band_edges(rate)
            self.assertEqual(len(edges), spectrum.BARS)
            for (lo, hi), (next_lo, _) in zip(edges, edges[1:]):
                self.assertEqual(hi, next_lo)
            for lo, hi in edges:
                self.assertLess(lo, hi)
                self.assertGreaterEqual(lo, 1)
                self.assertLessEqual(hi, spectrum.WINDOW // 2)

    def test_log_spaced_from_bass_to_treble(self):
        edges = spectrum.band_edges(RATE)
        hz = RATE / spectrum.WINDOW
        self.assertLess(edges[0][0] * hz, 60)
        self.assertGreater(edges[-1][1] * hz, 10000)


class LevelTests(unittest.TestCase):
    def test_full_scale_tone_fills_its_bar_and_leaves_the_far_ones(self):
        for hz in (100, 1000, 6000):
            bars = spectrum.levels(tone(hz), RATE)
            home = bar_for(hz)
            self.assertGreaterEqual(bars[home], 250, (hz, bars))
            for i, level in enumerate(bars):
                if abs(i - home) > 2:
                    self.assertEqual(level, 0, (hz, bars))

    def test_the_scale_is_decibels(self):
        # Half amplitude is -6 dB: 54/60 of the way up the bar.
        bars = spectrum.levels(tone(1000, 0.5), RATE)
        self.assertAlmostEqual(bars[bar_for(1000)], 255 * 54 / 60, delta=4)

    def test_silence_is_all_zero(self):
        self.assertEqual(spectrum.levels([0.0] * spectrum.WINDOW, RATE),
                         [0] * spectrum.BARS)


class WireTests(unittest.TestCase):
    def test_frame_line(self):
        self.assertEqual(spectrum.frame_line([0, 15, 16, 255] + [0] * 12),
                         b"000f10ff" + b"00" * 12 + b"\n")

    def test_header(self):
        self.assertEqual(spectrum.read_header(b"rate=24000\n"), 24000)
        for line in (b"", b"rate=\n", b"rate=abc\n", b"rate=100\n", b"hello\n",
                     b"rate=999999\n"):
            self.assertIsNone(spectrum.read_header(line), line)


class _Process:
    def __init__(self, stdout):
        self.stdout = io.BytesIO(stdout)
        self.stdin = mock.Mock()
        self.killed = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


class HelperSourceTests(unittest.TestCase):
    def test_reads_the_rate_then_pcm(self):
        process = _Process(b"rate=24000\n\x01\x00\x02\x00")
        source = spectrum.HelperSource(["tap"], popen=lambda *a, **k: process)
        rate, read = source.open()
        self.assertEqual(rate, 24000)
        self.assertEqual(read(4096), b"\x01\x00\x02\x00")
        source.close()
        process.stdin.close.assert_called_once()

    def test_no_header_is_an_error_and_the_process_is_ended(self):
        process = _Process(b"garbage\n")
        source = spectrum.HelperSource(["tap"], popen=lambda *a, **k: process)
        with self.assertRaises(OSError):
            source.open()
        process.stdin.close.assert_called_once()


class SourceForTests(unittest.TestCase):
    def test_an_unknown_platform_says_why(self):
        factory, reason = spectrum.source_for("sunos5")
        self.assertIsNone(factory)
        self.assertIn("sunos5", reason)

    def test_macos_without_the_helper_names_the_build(self):
        factory, reason = spectrum.source_for("darwin", helper="/nonexistent/spectrum-tap")
        self.assertIsNone(factory)
        self.assertIn("swiftc", reason)

    def test_macos_with_the_helper(self):
        with mock.patch("os.access", return_value=True):
            factory, reason = spectrum.source_for("darwin", helper="/x/spectrum-tap")
        self.assertIsNone(reason)
        self.assertEqual(factory().argv, ["/x/spectrum-tap"])
        self.assertIsNone(factory().rate)

    def test_windows_without_the_helper_names_the_compiler(self):
        factory, reason = spectrum.source_for("win32", helper="/nonexistent/spectrum-tap.exe")
        self.assertIsNone(factory)
        self.assertIn("csc.exe", reason)

    def test_windows_with_the_helper(self):
        with mock.patch("os.path.isfile", return_value=True):
            factory, reason = spectrum.source_for("win32", helper="C:/x/spectrum-tap.exe")
        self.assertIsNone(reason)
        self.assertEqual(factory().argv, ["C:/x/spectrum-tap.exe"])

    def test_linux_without_parec_names_the_package(self):
        factory, reason = spectrum.source_for("linux", which=lambda name: None)
        self.assertIsNone(factory)
        self.assertIn("libpulse", reason)

    def test_linux_records_the_default_monitor_at_a_fixed_rate(self):
        factory, reason = spectrum.source_for("linux", which=lambda name: "/usr/bin/" + name)
        self.assertIsNone(reason)
        source = factory()
        self.assertEqual(source.rate, spectrum.LINUX_RATE)
        self.assertEqual(source.argv[0], "parec")
        for argument in ("--device=@DEFAULT_MONITOR@", "--format=s16le",
                         f"--rate={spectrum.LINUX_RATE}", "--channels=1"):
            self.assertIn(argument, source.argv)


class FixedRateSourceTests(unittest.TestCase):
    def test_no_header_is_read_when_the_rate_is_fixed(self):
        process = _Process(b"\x01\x00\x02\x00")
        calls = []

        def popen(argv, **kwargs):
            calls.append(kwargs)
            return process

        rate, read = spectrum.HelperSource(["parec"], rate=24000, popen=popen).open()
        self.assertEqual(rate, 24000)
        self.assertEqual(read(4096), b"\x01\x00\x02\x00")
        self.assertIn("creationflags", calls[0])


class _FakeSource:
    """A tone for ever, until closed. Counts opens and closes."""

    opened = 0
    closed = 0

    def __init__(self):
        self.done = threading.Event()

    def open(self):
        type(self).opened += 1
        pcm = b"".join(int(s * 20000).to_bytes(2, "little", signed=True)
                       for s in tone(1000, n=1200))

        def read(n):
            if self.done.wait(0.01):
                return b""
            return pcm

        return RATE, read

    def close(self):
        if not self.done.is_set():
            type(self).closed += 1
        self.done.set()


class HubTests(unittest.TestCase):
    def setUp(self):
        _FakeSource.opened = _FakeSource.closed = 0
        patches = [mock.patch.object(spectrum, "LINGER_S", 0.2),
                   mock.patch.object(spectrum, "RESTART_S", 0.05)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_starts_on_the_first_watcher_and_stops_after_the_last(self):
        hub = spectrum.Spectrum(_FakeSource, log=lambda m: None)
        self.assertEqual(_FakeSource.opened, 0)
        frames = hub.frames()
        first = next(frames)
        self.assertEqual(len(first), spectrum.BARS * 2 + 1)
        lit = next(frames)
        self.assertEqual(bytes.fromhex(lit.decode().strip())[bar_for(1000)] > 200, True)
        self.assertEqual(_FakeSource.opened, 1)
        frames.close()
        deadline = time.monotonic() + 3
        while _FakeSource.closed == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(_FakeSource.closed, 1)

    def test_two_watchers_share_one_source(self):
        hub = spectrum.Spectrum(_FakeSource, log=lambda m: None)
        a, b = hub.frames(), hub.frames()
        next(a), next(b), next(a), next(b)
        self.assertEqual(_FakeSource.opened, 1)
        a.close()
        next(b)
        self.assertEqual(_FakeSource.closed, 0)
        b.close()

    def _manual(self, clock):
        hub = spectrum.Spectrum(lambda: None, clock=lambda: clock[0], log=lambda m: None)
        hub._running = True  # no capture thread: frames are published by hand
        return hub

    def test_an_unchanged_silent_frame_waits_for_the_keepalive(self):
        clock = [0.0]
        hub = self._manual(clock)
        frames = hub.frames()
        self.assertEqual(next(frames), spectrum.SILENT_FRAME)
        results = []
        reader = threading.Thread(target=lambda: results.append(next(frames)), daemon=True)
        reader.start()
        hub._publish([0] * spectrum.BARS)  # the same frame: not sent
        clock[0] = spectrum.KEEPALIVE_S - 0.1
        hub._publish([0] * spectrum.BARS)
        time.sleep(0.05)
        self.assertEqual(results, [])
        clock[0] = spectrum.KEEPALIVE_S
        hub._publish([0] * spectrum.BARS)
        reader.join(2)
        self.assertEqual(results, [spectrum.SILENT_FRAME])
        frames.close()

    def test_an_unchanged_frame_with_sound_is_resent_often(self):
        # A sustained note makes identical frames; the page counts a frame
        # older than 400 ms as silence, so the stream must repeat it.
        clock = [0.0]
        hub = self._manual(clock)
        frames = hub.frames()
        next(frames)
        hub._publish([7] * spectrum.BARS)
        self.assertEqual(next(frames), spectrum.frame_line([7] * spectrum.BARS))
        results = []
        reader = threading.Thread(target=lambda: results.append(next(frames)), daemon=True)
        reader.start()
        hub._publish([7] * spectrum.BARS)
        time.sleep(0.05)
        self.assertEqual(results, [])
        clock[0] = spectrum.RESEND_S
        hub._publish([7] * spectrum.BARS)
        reader.join(2)
        self.assertEqual(results, [spectrum.frame_line([7] * spectrum.BARS)])
        frames.close()

    def test_a_stream_ends_at_its_time_limit(self):
        clock = [0.0]
        hub = spectrum.Spectrum(lambda: None, clock=lambda: clock[0], log=lambda m: None)
        hub._running = True
        frames = hub.frames()
        next(frames)
        clock[0] = spectrum.MAX_STREAM_S
        self.assertEqual(list(frames), [])
        self.assertEqual(hub._watchers, 0)

    def test_the_stop_is_final_even_if_a_watcher_arrives_right_after(self):
        # The race: the pump sees nobody watching and stops; before the
        # capture thread is gone, a new watcher arrives (and would start a
        # thread of its own). The old thread must not see it and carry on.
        hub = spectrum.Spectrum(_FakeSource, log=lambda m: None)
        hub._running = True
        hub._watchers = 1
        opened = []

        class Once(_FakeSource):
            def open(self):
                opened.append(1)

                def read(n):
                    with hub._cond:
                        hub._watchers = 0
                        hub._last_watcher_left = -1e9
                    return b"\x00\x00" * 64

                return RATE, read

        real_publish = hub._publish

        arrived = []

        def publish(bars):
            real_publish(bars)
            if not arrived:
                arrived.append(1)
                with hub._cond:
                    hub._watchers = 1

        hub.source_factory = Once
        hub._publish = publish
        with mock.patch.object(spectrum.time, "sleep"):
            hub._capture()
        self.assertEqual(opened, [1])

    def test_a_blocked_source_is_closed_after_the_linger(self):
        # A silent tap blocks in read(); only the timer can end it.
        class Blocking(_FakeSource):
            def open(self):
                type(self).opened += 1
                return RATE, lambda n: (self.done.wait(), b"")[1]

        hub = spectrum.Spectrum(Blocking, log=lambda m: None)
        frames = hub.frames()
        next(frames)
        frames.close()
        deadline = time.monotonic() + 3
        while Blocking.closed == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(Blocking.closed, 1)

    def test_a_reconnect_inside_the_linger_keeps_the_source(self):
        hub = spectrum.Spectrum(_FakeSource, log=lambda m: None)
        first = hub.frames()
        next(first)
        next(first)
        first.close()
        time.sleep(spectrum.LINGER_S / 4)
        second = hub.frames()
        next(second)
        time.sleep(spectrum.LINGER_S + 0.7)  # past the first departure's timer
        next(second)
        self.assertEqual((_FakeSource.opened, _FakeSource.closed), (1, 0))
        second.close()

    def test_an_old_timer_does_not_close_a_later_linger(self):
        clock = [0.0]
        hub = spectrum.Spectrum(lambda: None, clock=lambda: clock[0], log=lambda m: None)
        source = _FakeSource()
        hub._source = source
        # The first departure's timer fires at 10, just after a watcher came
        # back and left again at 10 - LINGER_S/2: that linger is still running.
        clock[0] = 10.0
        hub._last_watcher_left = 10.0 - spectrum.LINGER_S / 2
        hub._close_if_unwatched()
        self.assertFalse(source.done.is_set())
        clock[0] = 10.0 + spectrum.LINGER_S
        hub._close_if_unwatched()
        self.assertTrue(source.done.is_set())

    def test_any_failure_restarts_with_backoff_and_logs_once(self):
        logged, sleeps, opened = [], [], []
        hub = spectrum.Spectrum(None, log=logged.append)
        hub._running = True
        hub._watchers = 1

        class Broken(_FakeSource):
            def open(self):
                opened.append(1)
                if len(opened) == 4:
                    with hub._cond:
                        hub._watchers = 0
                        hub._last_watcher_left = -1e9
                raise AttributeError("not an OSError")

        hub.source_factory = Broken
        with mock.patch.object(spectrum.time, "sleep", sleeps.append):
            hub._capture()
        self.assertEqual(len(opened), 4)
        self.assertEqual(sleeps, [spectrum.RESTART_S, 2 * spectrum.RESTART_S,
                                  4 * spectrum.RESTART_S, 8 * spectrum.RESTART_S])
        self.assertEqual(len([m for m in logged if "source failed" in m]), 1)
        self.assertFalse(hub._running)

    def test_a_silent_source_is_reported_once(self):
        logged = []

        class Silent(_FakeSource):
            def open(self):
                return RATE, lambda n: (self.done.wait(), b"")[1]

        with mock.patch.object(spectrum, "SILENT_WARNING_S", 0.05):
            hub = spectrum.Spectrum(Silent, log=logged.append)
            frames = hub.frames()
            next(frames)
            time.sleep(0.2)
            frames.close()
        self.assertEqual(len([m for m in logged if "System Audio Recording" in m]), 1)


class _Hub:
    def __init__(self, lines=(b"00" * 16 + b"\n", b"ff" * 16 + b"\n")):
        self.lines = lines
        self.closed = threading.Event()

    def frames(self):
        try:
            yield from self.lines
        finally:
            self.closed.set()


def _app(hub=None, **config):
    return types.SimpleNamespace(config=dict(DEFAULT_CONFIG, **config), spectrum=hub)


class RouteTests(unittest.TestCase):
    def test_off_is_404(self):
        status, body, _, _ = route("GET", "/spectrum", _app(None), HOST)
        self.assertEqual((status, body), (404, b""))

    def test_on_is_a_stream(self):
        status, body, content_type, headers = route("GET", "/spectrum", _app(_Hub()), HOST)
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/plain"))
        self.assertIn(("Cache-Control", "no-store"), headers)
        self.assertEqual(list(body), list(_Hub().lines))

    def test_needs_the_key_when_private(self):
        app = _app(_Hub(), panel_key="k" * 32, tls_cert="c", tls_key="k")
        status, body, _, _ = route("GET", "/spectrum", app, HOST, "tls")
        self.assertEqual((status, json.loads(body)), (401, {"error": "unauthorized"}))
        status, _, _, _ = route("GET", "/spectrum", app,
                                dict(HOST, **{"X-Panel-Key": "k" * 32}), "tls")
        self.assertEqual(status, 200)

    def test_checks_the_host_first(self):
        status, _, _, _ = route("GET", "/spectrum", _app(_Hub()), {"Host": "evil.example"})
        self.assertEqual(status, 421)


class StreamOverSocketTests(unittest.TestCase):
    def _serve(self, hub):
        server = Server(("127.0.0.1", 0), partial(Handler, app=_app(hub)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        return http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)

    def test_head_sends_no_frames_and_counts_no_watcher(self):
        started = []

        class Hub(_Hub):
            def frames(self):
                started.append(1)
                return super().frames()

        hub = Hub()
        conn = self._serve(hub)
        conn.request("HEAD", "/spectrum")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.read(), b"")
        conn.close()
        # route() builds the generator, but HEAD must never start it: an
        # unstarted generator has not run a line, so no watcher was counted.
        self.assertTrue(hub.closed.wait(0.3) is False)

    def test_frames_arrive_and_the_generator_is_closed(self):
        hub = _Hub()
        conn = self._serve(hub)
        conn.request("GET", "/spectrum")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIsNone(resp.getheader("Content-Length"))
        self.assertEqual(resp.getheader("Connection"), "close")
        self.assertEqual(resp.read(), b"".join(hub.lines))
        conn.close()
        self.assertTrue(hub.closed.wait(2))


if __name__ == "__main__":
    unittest.main()
