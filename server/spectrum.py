"""The spectrum bars: what this PC is playing, as sixteen levels (T8.5).

[ADR 0021](../docs/adr/0021-the-spectrum-is-a-stream.md) is the decision. The
short version: a platform *source* hands over mono PCM, this module turns it
into bars twenty times a second, and `GET /spectrum` streams them to the
phone as one line of hex per frame, over one long-lived connection.

The math is pure and runs here, in Python, whatever the platform: the source
is the only per-OS part, and every source hands over mono 16-bit PCM.
- macOS: the Swift helper in `mac/spectrum_tap.swift` (a Core Audio tap).
- Windows: the C# helper in `win/spectrum_tap.cs` (WASAPI loopback).
- Linux: `parec` on the default output's monitor, which PipeWire's
  pulse layer and PulseAudio both answer.

Capture runs only while somebody is watching. The first stream starts the
source, and the source stops `LINGER_S` after the last one ends, so a PC
whose panel is dark is not recording anything.

Standard library only, like the rest of `server/`.
"""

import array
import cmath
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from server import actions

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
# ...and a frame with sound in it this often, well inside the page's 400 ms
# freshness window: a sustained note makes identical frames, and a frame the
# page has not heard again for that long reads as silence (found by review).
RESEND_S = 0.2
# How long one stream may last before the server ends it and the phone opens
# a new one. It bounds what a client that never reads can hold.
MAX_STREAM_S = 900.0
# How long to wait after the source dies before starting it again, doubled
# on each failure in a row up to RESTART_MAX_S: a helper that can never start
# (an older macOS, a PC with no default output) must not respawn every five
# seconds for as long as the panel is lit.
RESTART_S = 5.0
RESTART_MAX_S = 60.0
# No samples this long after starting: say why, once. On macOS it is nearly
# always the permission.
SILENT_WARNING_S = 5.0

HELPER = Path(__file__).resolve().parent / "mac" / "spectrum-tap"
HELPER_SOURCE = HELPER.parent / "spectrum_tap.swift"
WINDOWS_HELPER = Path(__file__).resolve().parent / "win" / "spectrum-tap.exe"
WINDOWS_HELPER_SOURCE = WINDOWS_HELPER.parent / "spectrum_tap.cs"
# What Linux records: the default sink's monitor, downmixed and resampled by
# the sound server itself, so parec's stdout is already what the hub reads.
LINUX_RATE = 24000
PAREC = "parec"
# The Linux volume watch (T8.7). `parec` hands over PCM and nothing else, so
# the level needs a second, much cheaper process: `pactl subscribe` sleeps
# until something in the sound server moves and costs nothing while nothing
# does. Measured on CachyOS: it line-buffers into a pipe, so the events
# arrive as they happen rather than in a block at exit.
PACTL = "pactl"


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


SILENT_FRAME = frame_line([0] * BARS)


def volume_line(level):
    """The output volume on the wire (T8.6): `v=` and 0..100 in decimal."""
    return b"v=%d\n" % level


def read_volume(text):
    """The level in a helper's `v=<0..100>` stderr line, or None if it is not one.

    Strict, because the line is the helper's and the number goes to the
    phone: one to three digits, nothing else, and never above 100.
    """
    text = text.strip()
    if not text.startswith("v="):
        return None
    digits = text[len("v="):]
    if not (1 <= len(digits) <= 3 and digits.isascii() and digits.isdigit()):
        return None
    level = int(digits)
    return level if level <= 100 else None


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
    """A capture process writing mono int16 PCM on stdout.

    `open()` starts it and returns `(rate, read)`, where `read(n)` returns up
    to `n` bytes of PCM and b"" once the process has gone. The rate is the
    helper's `rate=` line, or `rate` when the command's own arguments fix it
    (parec) and it writes no header. `close()` ends it: closing stdin is what
    the helpers wait for, and a kill backs that up.

    Its stderr is read on a thread of its own (T8.6). A `v=<level>` line is
    the output volume, which the Windows helper reports as it changes, and
    goes to `on_volume`; any other line is the helper's complaint and goes to
    `log`. Under pythonw nothing else would ever see it.
    """

    def __init__(self, argv, rate=None, popen=subprocess.Popen):
        self.argv = argv
        self.rate = rate
        self.popen = popen
        self.process = None
        self.on_volume = None
        self.log = None

    def watch_stderr(self, on_volume, log):
        """Where the helper's stderr lines go; the hub calls it before `open`."""
        self.on_volume = on_volume
        self.log = log

    def _drain_stderr(self, stream):
        try:
            for raw in iter(stream.readline, b""):
                text = raw.decode("ascii", "replace").strip()
                level = read_volume(text)
                if level is not None:
                    if self.on_volume is not None:
                        self.on_volume(level)
                elif text and self.log is not None:
                    self.log(f"spectrum: helper says: {text[:200]}")
        except (OSError, ValueError):
            # The pipe closed under the read: the helper has gone.
            pass

    def open(self):
        # CREATE_NO_WINDOW: the server runs under pythonw on Windows, and a
        # console program started from it opens a window of its own, which
        # would sit on the owner's desktop for as long as the panel watched.
        self.process = self.popen(
            self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Local: close() may run from the linger timer at any moment and
        # clears self.process (found by review).
        process = self.process
        # Drained whatever it carries: a pipe nobody reads fills, and the
        # helper then blocks on its next complaint.
        stderr = getattr(process, "stderr", None)
        if stderr is not None:
            threading.Thread(target=self._drain_stderr, args=(stderr,),
                             name="spectrum-stderr", daemon=True).start()
        rate = self.rate
        if rate is None:
            rate = read_header(process.stdout.readline())
        if rate is None:
            self.close()
            raise OSError("spectrum helper sent no rate line")
        return rate, process.stdout.read

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


class ParecSource(HelperSource):
    """The Linux source: `parec` for the PCM, `pactl subscribe` for the volume.

    T8.6 gave the level a ride on the stream and only Windows took it, where
    the helper reads the endpoint itself and prints `v=`. `parec` has no such
    read and never will, so on Linux the bar followed `/quotes` and sat up to
    `App.VOLUME_TTL_S` behind the knob (T8.7).

    This is the other half of the Windows helper, assembled out of two
    processes instead of one: `pactl subscribe` says *when*, and the same
    `wpctl get-volume` `/quotes` uses says *what*. Pushing it through
    `on_volume` -- the callback the stderr drain already owns -- means the hub,
    every open stream and `/quotes` end on one number, with no second path to
    keep in step.

    A read per event and not a poll: nothing runs while nothing moves, which
    is the property that lets this watch a desk all evening. `pactl` missing
    is not an error, only the old behaviour: the bar falls back to `/quotes`
    and the reason is logged once.
    """

    def __init__(self, argv, rate=None, popen=subprocess.Popen,
                 subscribe_argv=None, read_level=None, which=shutil.which):
        super().__init__(argv, rate=rate, popen=popen)
        self.subscribe_argv = subscribe_argv or volume_events_argv()
        self.read_level = read_level or actions.read_volume
        self.which = which
        self._events = None
        self._closed = False

    def open(self):
        # The PCM first: a volume watch that failed must not cost the bars,
        # which are the thing the stream is actually for.
        rate, read = super().open()
        self._watch_volume()
        return rate, read

    def _watch_volume(self):
        if self.on_volume is None:
            # `reports_volume` is off, or the volume action is: the hub wants
            # no level and `pactl` must not be started to throw one away.
            return
        if self.which(self.subscribe_argv[0]) is None:
            self._say(f"spectrum: no {self.subscribe_argv[0]} on PATH; the volume bar "
                      f"follows /quotes instead of the stream")
            return
        try:
            self._events = self.popen(
                self.subscribe_argv, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                # **LC_ALL=C, because the event lines are parsed.** `pactl`
                # binds the `pulseaudio` text domain and the line is the
                # translatable `Event '%s' on %s #%u`, so on a desktop with
                # the language pack installed every event arrives translated
                # and `is_sink_event` matches none of them -- the bar would
                # stop following the knob, silently, which is the very
                # symptom this task exists to fix. `actions._default_runner`
                # has forced it on this binary since T8.1 and says why at
                # length; the server inherits the graphical session's
                # environment (invariant 2), which is the one with a
                # language set. Found by review, on a box whose own locale
                # happened to be English.
                env=dict(os.environ, LC_ALL="C"))
        except OSError as exc:
            self._say(f"spectrum: the volume watch did not start: {exc}")
            return
        threading.Thread(target=self._drain_events, args=(self._events,),
                         name="spectrum-volume", daemon=True).start()

    def _drain_events(self, process):
        # The level on opening, before the first event: the hub cleared its
        # own when the last source went, and a desk where nobody touches the
        # knob would otherwise show no bar at all until somebody did.
        self._report()
        try:
            for raw in iter(process.stdout.readline, b""):
                if self._closed:
                    return
                if is_sink_event(raw.decode("ascii", "replace")):
                    self._report()
        except (OSError, ValueError):
            # The pipe closed under the read: the watch has gone with close().
            return
        if self._closed:
            return
        # End of stream with nobody having closed us: the watch died on its
        # own. `pactl` with no sound server to reach answers `Connection
        # failure` and exits at once, and without this the bar would drop
        # back to /quotes while the log said nothing -- which is not what
        # ADR 0021 and SERVER-SETUP promise. Its stderr is at most the one
        # line it exits on, so reading it here cannot block the writer.
        self._say("spectrum: the volume watch ended; the bar follows /quotes"
                  + self._complaint(process))

    @staticmethod
    def _complaint(process):
        stream = getattr(process, "stderr", None)
        if stream is None:
            return ""
        try:
            text = (stream.read() or b"").decode("ascii", "replace").strip()
        except (OSError, ValueError):
            return ""
        return f": {text[:200]}" if text else ""

    def _report(self):
        # `actions.read_volume` never raises and answers None when no mixer
        # replies; `note_volume` drops a None and an unchanged level itself.
        on_volume = self.on_volume
        if on_volume is None:
            return
        level = self.read_level()
        # The read spawns `wpctl` and can outlive `close()`. The hub clears
        # its level when a source goes, precisely so the next stream does not
        # open on a dead source's number; a late answer here would put one
        # straight back. Checked after the read, not before (review, T8.7).
        if not self._closed:
            on_volume(level)

    def _say(self, message):
        if self.log is not None:
            self.log(message)

    def close(self):
        # Before terminating, so a read already in flight is dropped rather
        # than delivered into a hub that has forgotten this source.
        self._closed = True
        events, self._events = self._events, None
        if events is not None:
            try:
                events.terminate()
                events.wait(timeout=2)
            except subprocess.TimeoutExpired:
                events.kill()
                events.wait()
            except OSError:
                pass
        super().close()


def parec_argv():
    """The Linux source: the default output's monitor, as the hub reads it."""
    return [PAREC, "--device=@DEFAULT_MONITOR@", "--format=s16le",
            f"--rate={LINUX_RATE}", "--channels=1", "--latency-msec=25"]


def volume_events_argv():
    """The Linux volume watch (T8.7): one line out of the sound server per change."""
    return [PACTL, "subscribe"]


def is_sink_event(text):
    """Pure: does this `pactl subscribe` line mean the output volume may have moved?

    Measured against CachyOS, where one `wpctl set-volume` prints exactly
    `Event 'change' on sink #57`. Two near-misses are deliberately excluded:

    - `sink-input #N` is one application's own slider, not the device's, and
      a video raising its stream must not redraw the panel's bar. The ` #`
      in the match is what separates them -- `sink-input #` is not `sink #`.
    - `source` is a microphone, which the bar does not show.

    `server` is kept: a change of default sink arrives as that, and the new
    sink's level is a different number from the old one's.
    """
    text = text.strip()
    if not text.startswith("Event "):
        return False
    return " on sink #" in text or text.endswith(" on server") or " on server #" in text


def source_for(platform=sys.platform, helper=None, which=shutil.which):
    """A zero-argument factory for this platform's source, or None with a reason.

    Returns `(factory, None)` or `(None, reason)`; the reason is what `main`
    prints, so an owner who turned `spectrum` on learns why it stays flat.
    """
    if platform == "darwin":
        helper = helper or HELPER
        if not os.access(helper, os.X_OK):
            return None, (f"{helper} is missing; build it with: swiftc -O "
                          f"{HELPER_SOURCE} -o {helper} (install_agent.sh does)")
        return (lambda: HelperSource([str(helper)])), None
    if platform == "win32":
        helper = helper or WINDOWS_HELPER
        if not os.path.isfile(helper):
            return None, (f"{helper} is missing; install_task.ps1 compiles it from "
                          f"{WINDOWS_HELPER_SOURCE} with the csc.exe in .NET Framework 4")
        return (lambda: HelperSource([str(helper)])), None
    if platform.startswith("linux"):
        if which(PAREC) is None:
            return None, ("no parec on PATH; it comes with libpulse (Arch, CachyOS) "
                          "or pulseaudio-utils (Debian, Fedora)")
        return (lambda: ParecSource(parec_argv(), rate=LINUX_RATE)), None
    return None, f"no audio capture on {platform}"


def reports_volume(platform=sys.platform, which=shutil.which):
    """Pure-ish: does this platform's source send the level up the stream?

    Windows reads the endpoint inside its helper (T8.6); Linux watches
    `pactl subscribe` beside `parec` (T8.7) and so needs `pactl` on PATH,
    even though the level itself may come back from `wpctl`.

    macOS is the remaining False: the Swift helper has no volume read yet, so
    its bar still follows `/quotes`. The hub is told, rather than guessing,
    because a hub that heard no level must not claim one.
    """
    if platform == "win32":
        return True
    if platform.startswith("linux"):
        return which(PACTL) is not None
    return False


class Spectrum:
    """Runs one source for any number of streams and fans its frames out.

    `frames()` is a generator of wire lines for one stream. The first one
    starts the capture thread; the thread stops `LINGER_S` after the last
    stream closes. A source that dies is restarted after `RESTART_S` for as
    long as somebody is still watching.

    It also carries the output volume (T8.6), once `on_volume` is set: a
    source that reports it (the Windows helper) feeds `note_volume`, every
    stream gets a `v=<level>` line when the level changes and one on opening,
    and `on_volume` is told, so `/quotes` says the same number. With
    `on_volume` left None -- the `volume` action not enabled -- no volume
    line is ever written.

    `reports_volume` says whether this platform's source sends the level at
    all. Only then does the App wire `on_volume`: a hub that heard only the
    phone's sets would open every new stream with the last one, however far
    the knob had moved since (found by review). The level is forgotten when
    the source closes, for the same reason.
    """

    def __init__(self, source_factory, clock=time.monotonic, log=None,
                 reports_volume=False):
        self.source_factory = source_factory
        self.clock = clock
        self.log = log or (lambda message: print(message, file=sys.stderr))
        self.reports_volume = reports_volume
        self.on_volume = None
        self._cond = threading.Condition()
        self._watchers = 0
        self._last_watcher_left = None
        self._running = False
        self._frame = frame_line([0] * BARS)
        self._sequence = 0
        self._volume = None
        self._volume_sequence = 0
        self._source = None
        self._heard = False
        self._warned = False

    def note_volume(self, level):
        """A measured output volume, 0..100: to every stream, if it changed."""
        owner = self.on_volume
        if owner is None or level is None:
            return
        # The owner is told under the lock: two threads noting two levels
        # must reach the App in the order the hub kept them, or /quotes can
        # end on the older one (found by review). The App takes only its own
        # lock in there, and never holds it while taking this one.
        with self._cond:
            if level == self._volume:
                return
            self._volume = level
            self._volume_sequence += 1
            self._cond.notify_all()
            owner(level)

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
            # A timer from an earlier departure, with a watcher who came and
            # went since: the linger runs from the latest one (found by
            # review), and that one's own timer comes later.
            left = self._last_watcher_left
            if left is not None and self.clock() - left < LINGER_S:
                return
            source = self._source
        if source is not None:
            source.close()

    def _capture(self):
        # Every exit goes through _should_run returning False, which clears
        # _running under the lock in the same breath, and the first False is
        # final. A watcher arriving after it starts a fresh thread; if this
        # one asked again it could see that watcher and live on beside it.
        failures = 0
        while self._should_run():
            stopped = False
            heard = False
            source = self.source_factory()
            watch = getattr(source, "watch_stderr", None)
            if watch is not None:
                # None when nobody wants a level -- `reports_volume` off, or
                # the `volume` action not enabled. `note_volume` would drop
                # it anyway, but a source that is told so can decline to go
                # looking: on Linux the difference is a `pactl subscribe`
                # process and a `wpctl` per sink change, spent on a mixer the
                # owner disabled (review, T8.7).
                watch(self.note_volume if self.on_volume is not None else None, self.log)
            with self._cond:
                self._source = source
            self._heard = False
            timer = threading.Timer(SILENT_WARNING_S, self._warn_if_silent)
            timer.daemon = True
            try:
                rate, read = source.open()
                timer.start()
                stopped = self._pump(rate, read)
                heard = self._heard
            except Exception as exc:  # noqa: BLE001 - the thread must not die
                # Everything, not only OSError: an exception that escaped
                # here would leave _running set with no thread behind it, and
                # the bars would stay flat until the server restarted.
                if failures == 0:
                    self.log(f"spectrum: source failed: {exc.__class__.__name__}: {exc}")
            finally:
                timer.cancel()
                with self._cond:
                    self._source = None
                    # A level from a helper that has gone is not one to open
                    # the next stream with; the next helper reports afresh.
                    if self._volume is not None:
                        self._volume = None
                        self._volume_sequence += 1
                source.close()
            self._publish([0] * BARS)
            if stopped:
                return
            failures = 0 if heard else failures + 1
            time.sleep(min(RESTART_MAX_S, RESTART_S * 2 ** max(0, failures - 1)))

    def _warn_if_silent(self):
        if not self._heard and not self._warned:
            self._warned = True
            self.log("spectrum: the source has sent no audio yet. Nothing may be "
                     "playing; on macOS, also check that System Audio Recording is "
                     "allowed for the server's python (Privacy & Security)")

    def _pump(self, rate, read):
        """Reads PCM until the source ends (False) or nobody is watching (True).

        True means `_should_run` has already said stop, so the caller must
        exit without asking again.
        """
        hop = rate // FPS
        window_fn = hann(WINDOW)
        edges = band_edges(rate, WINDOW)
        ring = [0.0] * WINDOW
        pending = 0
        leftover = b""
        while self._should_run():
            chunk = read(4096)
            if not chunk:
                return False
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
        return True

    # -- the stream side ---------------------------------------------------

    def frames(self):
        """Wire lines for one stream: a frame when one changes, a keepalive otherwise.

        And the volume (T8.6): the last known level first, then a line each
        time it changes. It does not count as a write for the keepalive: a
        frame is what the phone's freshness check is about.
        """
        with self._cond:
            self._watchers += 1
            self._start_locked()
        try:
            opened = self.clock()
            sent_sequence = -1
            sent_frame = None
            sent_volume = -1
            last_write = opened
            while self.clock() - opened < MAX_STREAM_S:
                with self._cond:
                    if self._sequence == sent_sequence and self._volume_sequence == sent_volume:
                        self._cond.wait(timeout=1.0)
                    sequence, frame = self._sequence, self._frame
                    volume_sequence, volume = self._volume_sequence, self._volume
                if volume_sequence != sent_volume:
                    sent_volume = volume_sequence
                    if volume is not None and self.on_volume is not None:
                        yield volume_line(volume)
                now = self.clock()
                if sequence != sent_sequence and frame != sent_frame:
                    sent_sequence, sent_frame, last_write = sequence, frame, now
                    yield frame
                elif frame != SILENT_FRAME and now - last_write >= RESEND_S:
                    sent_sequence, last_write = sequence, now
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
