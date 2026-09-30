"""The spectrum bars: what this PC is playing, as sixteen levels (T8.5).

[ADR 0021](../docs/adr/0021-the-spectrum-is-a-stream.md) is the decision. The
short version: a platform *source* hands over mono PCM, this module turns it
into bars twenty times a second, and `GET /spectrum` streams them to the
phone as one line of hex per frame, over one long-lived connection.

The math is pure and runs here, in Python, whatever the platform: the source
is the only per-OS part. macOS is the one implemented, through the Swift
helper in `mac/spectrum_tap.swift`; Windows (WASAPI loopback) and Linux (a
`.monitor` source) plug into the same `Spectrum` hub when they come.

Capture runs only while somebody is watching. The first stream starts the
source, and the source stops `LINGER_S` after the last one ends, so a PC
whose panel is dark is not recording anything.

Standard library only, like the rest of `server/`.
"""

import array
import cmath
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BARS = 16
FPS = 20
# 1024 samples at 24 kHz: 43 ms of sound and 23 Hz per bin, which is enough
# to give the lowest bar a bin of its own. Frames overlap (1200 new samples
# per frame at 24 kHz), which is what a hop shorter than the window means.
WINDOW = 1024
LOW_HZ = 50.0
HIGH_HZ = 11000.0
# The quietest level that still lights a bar, and 0 dBFS lights it full. A bin
# of music sits around -20 to -40 dB, so the range puts it mid-bar.
FLOOR_DB = -60.0

# How long the source keeps running after the last stream ends. Long enough
# that the phone reconnecting after a dropped socket does not restart the
# helper, and so re-ask macOS for the tap.
LINGER_S = 5.0
# A stream re-sends its last frame this often when nothing has changed. The
# write is what finds a phone that vanished without closing the socket.
KEEPALIVE_S = 5.0
# How long one stream may last before the server ends it and the phone opens
# a new one. It bounds what a client that never reads can hold.
MAX_STREAM_S = 900.0
# How long to wait after the source dies before starting it again.
RESTART_S = 5.0
# No samples this long after starting: say why, once. On macOS it is nearly
# always the permission.
SILENT_WARNING_S = 5.0

HELPER = Path(__file__).resolve().parent / "mac" / "spectrum-tap"
HELPER_SOURCE = HELPER.parent / "spectrum_tap.swift"


def fft(re, im):
    """In-place iterative radix-2 FFT of two float lists of equal power-of-2 length."""
    n = len(re)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]
    size = 2
    while size <= n:
        half = size >> 1
        step = -2.0 * math.pi / size
        for k in range(half):
            w = cmath.exp(complex(0.0, step * k))
            wr, wi = w.real, w.imag
            for start in range(k, n, size):
                a = start + half
                tr = wr * re[a] - wi * im[a]
                ti = wr * im[a] + wi * re[a]
                re[a] = re[start] - tr
                im[a] = im[start] - ti
                re[start] += tr
                im[start] += ti
        size <<= 1


def hann(n):
    """The Hann window of length `n`."""
    return [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)) for i in range(n)]


def band_edges(rate, window=WINDOW, bars=BARS, low=LOW_HZ, high=HIGH_HZ):
    """`bars` half-open bin ranges `(lo, hi)`, log-spaced from `low` to `high` Hz.

    Every range holds at least one bin and none overlaps the next, so at low
    frequencies, where a log step is narrower than a bin, neighbouring bars
    take consecutive bins rather than sharing one.
    """
    nyquist_bin = window // 2
    hz_per_bin = rate / window
    high = min(high, rate / 2.0 * 0.95)
    edges = []
    previous = max(1, int(low / hz_per_bin))
    for i in range(1, bars + 1):
        hz = low * (high / low) ** (i / bars)
        upper = min(nyquist_bin, max(previous + 1, int(round(hz / hz_per_bin))))
        edges.append((previous, upper))
        previous = upper
    return edges


def levels(samples, rate, window_fn=None, edges=None):
    """Bars for one window of `samples` (floats in -1..1): `BARS` ints, 0..255.

    Each bar is the loudest bin in its range, in dB against full scale, mapped
    from `FLOOR_DB`..0 onto 0..255. A full-scale sine is 255 in its bar.
    """
    n = len(samples)
    window_fn = window_fn or hann(n)
    edges = edges or band_edges(rate, n)
    re = [s * w for s, w in zip(samples, window_fn)]
    im = [0.0] * n
    fft(re, im)
    # 2/sum(window) makes a full-scale sine exactly 1.0 in its bin.
    scale = 2.0 / sum(window_fn)
    out = []
    for lo, hi in edges:
        peak = max(re[k] * re[k] + im[k] * im[k] for k in range(lo, hi))
        amplitude = math.sqrt(peak) * scale
        db = 20.0 * math.log10(amplitude) if amplitude > 0 else FLOOR_DB
        level = (db - FLOOR_DB) / -FLOOR_DB
        out.append(max(0, min(255, int(round(level * 255)))))
    return out


def frame_line(bars):
    """One frame on the wire: two hex digits per bar and a newline."""
    return bytes(bars).hex().encode("ascii") + b"\n"


def read_header(line):
    """The rate in a helper's `rate=<hz>` line, or None if it is not one."""
    text = line.decode("ascii", "replace").strip()
    if not text.startswith("rate="):
        return None
    try:
        rate = int(text[len("rate="):])
    except ValueError:
        return None
    return rate if 8000 <= rate <= 192000 else None


class HelperSource:
    """A capture process speaking the helper protocol on stdout.

    `open()` starts it and returns `(rate, read)`, where `read(n)` returns up
    to `n` bytes of PCM and b"" once the process has gone. `close()` ends it:
    closing stdin is what the helper waits for, and a kill backs that up.
    """

    def __init__(self, argv, popen=subprocess.Popen):
        self.argv = argv
        self.popen = popen
        self.process = None

    def open(self):
        self.process = self.popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        rate = read_header(self.process.stdout.readline())
        if rate is None:
            self.close()
            raise OSError("spectrum helper sent no rate line")
        return rate, self.process.stdout.read

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait()


def source_for(platform=sys.platform, helper=HELPER):
    """A zero-argument factory for this platform's source, or None with a reason.

    Returns `(factory, None)` or `(None, reason)`; the reason is what `main`
    prints, so an owner who turned `spectrum` on learns why it stays flat.
    """
    if platform == "darwin":
        if not os.access(helper, os.X_OK):
            return None, (f"{helper} is missing; build it with: swiftc -O "
                          f"{HELPER_SOURCE} -o {helper} (install_agent.sh does)")
        return (lambda: HelperSource([str(helper)])), None
    return None, f"no audio capture on {platform} yet (macOS only, T8.5)"


class Spectrum:
    """Runs one source for any number of streams and fans its frames out.

    `frames()` is a generator of wire lines for one stream. The first one
    starts the capture thread; the thread stops `LINGER_S` after the last
    stream closes. A source that dies is restarted after `RESTART_S` for as
    long as somebody is still watching.
    """

    def __init__(self, source_factory, clock=time.monotonic, log=None):
        self.source_factory = source_factory
        self.clock = clock
        self.log = log or (lambda message: print(message, file=sys.stderr))
        self._cond = threading.Condition()
        self._watchers = 0
        self._last_watcher_left = None
        self._running = False
        self._frame = frame_line([0] * BARS)
        self._sequence = 0
        self._source = None
        self._heard = False
        self._warned = False

    # -- the capture side --------------------------------------------------

    def _start_locked(self):
        if not self._running:
            self._running = True
            threading.Thread(target=self._capture, name="spectrum", daemon=True).start()

    def _should_run(self):
        with self._cond:
            if self._watchers > 0:
                return True
            left = self._last_watcher_left
            if left is not None and self.clock() - left < LINGER_S:
                return True
            self._running = False
            return False

    def _publish(self, bars):
        with self._cond:
            self._frame = frame_line(bars)
            self._sequence += 1
            self._cond.notify_all()

    def _close_if_unwatched(self):
        """Ends the source once nobody is watching.

        From a timer, not the capture thread: that thread is blocked in a read
        whenever the source is silent, which is exactly when nothing else
        would wake it.
        """
        with self._cond:
            if self._watchers > 0:
                return
            source = self._source
        if source is not None:
            source.close()

    def _capture(self):
        while self._should_run():
            source = self.source_factory()
            with self._cond:
                self._source = source
            self._heard = False
            timer = threading.Timer(SILENT_WARNING_S, self._warn_if_silent)
            timer.daemon = True
            try:
                rate, read = source.open()
                timer.start()
                self._pump(rate, read)
            except OSError as exc:
                self.log(f"spectrum: source failed: {exc}")
            finally:
                timer.cancel()
                with self._cond:
                    self._source = None
                source.close()
            self._publish([0] * BARS)
            if self._should_run():
                time.sleep(RESTART_S)

    def _warn_if_silent(self):
        if not self._heard and not self._warned:
            self._warned = True
            self.log("spectrum: the source has sent no audio; on macOS, allow "
                     "System Audio Recording for the server's python in System "
                     "Settings > Privacy & Security")

    def _pump(self, rate, read):
        """Reads PCM until the source ends or nobody is watching."""
        hop = rate // FPS
        window_fn = hann(WINDOW)
        edges = band_edges(rate, WINDOW)
        ring = [0.0] * WINDOW
        pending = 0
        leftover = b""
        while self._should_run():
            chunk = read(4096)
            if not chunk:
                return
            self._heard = True
            data = leftover + chunk
            usable = len(data) - len(data) % 2
            leftover = data[usable:]
            samples = array.array("h")
            samples.frombytes(data[:usable])
            if sys.byteorder != "little":
                samples.byteswap()
            ring.extend(s / 32768.0 for s in samples)
            del ring[:-WINDOW]
            pending += len(samples)
            if pending >= hop:
                pending %= hop
                self._publish(levels(ring, rate, window_fn, edges))

    # -- the stream side ---------------------------------------------------

    def frames(self):
        """Wire lines for one stream: a frame when one changes, a keepalive otherwise."""
        with self._cond:
            self._watchers += 1
            self._start_locked()
        try:
            opened = self.clock()
            sent_sequence = -1
            sent_frame = None
            last_write = opened
            while self.clock() - opened < MAX_STREAM_S:
                with self._cond:
                    if self._sequence == sent_sequence:
                        self._cond.wait(timeout=1.0)
                    sequence, frame = self._sequence, self._frame
                now = self.clock()
                if sequence != sent_sequence and frame != sent_frame:
                    sent_sequence, sent_frame, last_write = sequence, frame, now
                    yield frame
                elif now - last_write >= KEEPALIVE_S:
                    sent_sequence, last_write = sequence, now
                    yield sent_frame or frame
                else:
                    sent_sequence = sequence
        finally:
            with self._cond:
                self._watchers -= 1
                if self._watchers == 0:
                    self._last_watcher_left = self.clock()
                    timer = threading.Timer(LINGER_S + 0.5, self._close_if_unwatched)
                    timer.daemon = True
                    timer.start()
