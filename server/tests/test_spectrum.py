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
    def test_other_platforms_say_why(self):
        for platform in ("win32", "linux"):
            factory, reason = spectrum.source_for(platform)
            self.assertIsNone(factory)
            self.assertIn(platform, reason)

    def test_macos_without_the_helper_names_the_build(self):
        factory, reason = spectrum.source_for("darwin", helper="/nonexistent/spectrum-tap")
        self.assertIsNone(factory)
        self.assertIn("swiftc", reason)

    def test_macos_with_the_helper(self):
        with mock.patch("os.access", return_value=True):
            factory, reason = spectrum.source_for("darwin", helper="/x/spectrum-tap")
        self.assertIsNone(reason)
        self.assertEqual(factory().argv, ["/x/spectrum-tap"])


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

    def test_an_unchanged_frame_is_not_resent_until_the_keepalive(self):
        clock = [0.0]
        hub = spectrum.Spectrum(lambda: None, clock=lambda: clock[0], log=lambda m: None)
        hub._running = True  # no capture thread: frames are published by hand
        frames = hub.frames()
        self.assertEqual(next(frames), spectrum.frame_line([0] * spectrum.BARS))
        hub._publish([0] * spectrum.BARS)
        hub._publish([7] * spectrum.BARS)
        self.assertEqual(next(frames), spectrum.frame_line([7] * spectrum.BARS))
        hub._publish([7] * spectrum.BARS)
        clock[0] = spectrum.KEEPALIVE_S
        self.assertEqual(next(frames), spectrum.frame_line([7] * spectrum.BARS))
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
    def test_frames_arrive_and_the_generator_is_closed(self):
        hub = _Hub()
        server = Server(("127.0.0.1", 0), partial(Handler, app=_app(hub)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
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
