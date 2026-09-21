"""Drive the night profile on the real phone and assert the marker. Exits non-zero on failure.

    python e2e/check_night_marker.py [--config PATH] [--wait SECONDS]

T6.4's native half. The page's half is a browser check
(`e2e/layout/check_night.py`); this is the part no browser can see -- the
window's `screenBrightness`, which only a real Activity has -- and the app's
own evidence for it is the `night=` marker, because Android exposes no
documented way to read a window's brightness back from adb (ADR 0009).

**The marker is emitted on transitions only**, like `state=`, `screen=` and
`dormant=` before it, so `logcat -c && sleep 90 && grep night=on` cannot work:
with nothing changing there is nothing to log, and the grep would be waiting
for a line the app is right not to write. The transition has to be *driven*,
and the only input a test can reach is the one the window is configured
through -- the two bounds in the PC's config. Three questions, in order:

  1. **a steady panel logs nothing.** A day window, and not one `night=` line
     across a whole data cycle. This is what the original acceptance was
     reaching for, and it is the assertion that fails an implementation
     logging the marker on every refresh -- which is the one shape that would
     pass questions 2 and 3 for ever.
  2. **a window containing now turns it on.** The window changes, which means
     the server restarts.
  3. **the window ending turns it off, with nothing else moving.**

Question 3 is why the night window here is *ninety seconds long* rather than
two hours. The obvious way to drive the falling edge is another restart, and
the first cut did exactly that -- and passed for the wrong reason. A restart
is a gap in the server's answers, and a gap the probe ladder notices is a
logout as far as the phone is concerned: the panel goes offline, the profile
comes off with it, and `night=off` is logged by the blip rather than by the
window. It was recorded on the device, two lines apart:

    19:36:22 night=on
    19:36:24 state=offline
    19:36:24 screen=sleep
    19:36:24 night=off      <- not the window. The PC leaving.

The rising edge does not have this problem and needs no protection: a blip
can only ever *clear* the profile, never set it, so a `night=on` is
unforgeable by one. The falling edge is the one that had to stop depending on
a restart, so it does not use one -- the window simply expires while the
server sits there answering, which is also what happens at 07:00 every
morning.

The windows are computed from this machine's clock. That the *phone's* clock
is the one being compared against is not something this file can prove -- the
two are minutes apart on the same desk -- and it is covered where it can be:
`NightWindowTest` drives the predicate off a calendar it owns, and the
payload carries two strings rather than a boolean so that there is nothing
else it could be comparing.

Slow on purpose: a data cycle is 60s and this waits for three of them, so
budget about five minutes.

Requires: the phone on adb with the app installed, and port 8777 free -- this
script runs the server itself, because a config change is a restart and
restarting somebody's running server is not this script's to do.
"""

import argparse
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from server.config_format import ConfigError  # noqa: E402
from server.server import config_search_paths, load_config  # noqa: E402

SERVER = os.path.join(ROOT, "server", "server.py")
ACTIVITY = "dev.bosco.deskpanel/.MainActivity"
TAG = "DeskPanel"


def adb(*args, **kwargs):
    return subprocess.run(("adb",) + args, capture_output=True, text=True, **kwargs)


def hhmm(minute_of_day):
    minute_of_day %= 24 * 60
    return "%02d:%02d" % (minute_of_day // 60, minute_of_day % 60)


# How long the night window has left to run when the server is restarted into
# it. Long enough for the restart, the reconnect and one data cycle to land
# inside it; short enough that waiting for it to expire is not the whole
# afternoon. The panel enters the profile on the first refresh after the
# restart and leaves it on the first refresh after this many seconds.
NIGHT_SECONDS = 150

# DataPoller's interval. Every wait here is written in cycles rather than in
# seconds, because what is being waited for is always "the next refresh".
CYCLE_SECONDS = 60


def windows(now):
    """(night, day, seconds_to_end): a window ending shortly, and one three hours off.

    The night window starts an hour ago and ends NIGHT_SECONDS from now, so it
    contains this moment and stops containing it soon -- which is the whole
    trick that lets the falling edge be driven by the clock instead of by a
    restart. `start` is an hour back rather than a minute so that the restart
    and the reconnect cannot land before it.

    Both bounds are modular, so both wrap midnight when the clock does. That
    is not a special case being dodged: 22:00 to 07:00 is the shipped window's
    own shape, and it gets exercised here for free once a night.
    """
    minute = now.hour * 60 + now.minute
    # Rounded up: the payload's bounds have minute resolution, so a window
    # ending "in 150 seconds" ends at the top of the minute at or after that,
    # and rounding down would make it end early. The third value is how many
    # seconds that actually is from *now*, which is what the wait is written
    # against -- guessing it from NIGHT_SECONDS would be up to a minute out,
    # depending only on which second of the minute the run started in.
    ends_in = -(-NIGHT_SECONDS // 60)
    return ((hhmm(minute - 60), hhmm(minute + ends_in)),
            (hhmm(minute + 180), hhmm(minute + 240)),
            ends_in * 60 - now.second)


def port_free(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) != 0


class Server:
    """The PC server, run by this script so that a config change can restart it.

    A temporary JSON config rather than an edit in place: the real one is
    somebody's, and a test that rewrote it and then crashed would leave a desk
    panel dimming at the wrong hour with nothing to say why. `load_config`
    normalises TOML and JSON to the same dict, so the copy is valid whichever
    the original was.

    That copy carries whatever the real config carries, the brapi token
    included, so it is written with `mkstemp` -- 0600, owner only, never a
    predictable name in a world-readable directory -- and unlinked in `stop`,
    which every path through this script reaches through a `finally`. A
    `kill -9` would leak it; nothing short of that does.
    """

    def __init__(self, base_config, port):
        self.base = base_config
        self.port = port
        self.path = None
        self.proc = None

    def start(self, night_start, night_end):
        config = dict(self.base, night_start=night_start, night_end=night_end)
        fd, self.path = tempfile.mkstemp(prefix="desk-panel-night-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        self.proc = subprocess.Popen(
            [sys.executable, SERVER, "--config", self.path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/ping" % self.port, timeout=2):
                    return True
            except (urllib.error.URLError, OSError):
                time.sleep(0.3)
        return False

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.path is not None and os.path.exists(self.path):
            os.unlink(self.path)
            self.path = None


def nudge():
    """Put the panel back on screen after a restart.

    A restart is a gap in the server's answers, and a gap long enough for the
    probe ladder to notice is a real logout as far as the phone is concerned:
    the screen sleeps, the device dozes, and the app is left probing on a
    fifteen-minute alarm (T5.6). Coming back from that is T4.3's and T5.6's
    behaviour and they have their own acceptances; waiting on it here would
    make this file's answer depend on theirs and take a quarter of an hour to
    get it.

    It starts an Activity that is usually already running, which is a no-op
    when the restart was quick enough that the phone never noticed. It cannot
    put the panel into the night profile or out of it -- the only thing that
    does that is the window in the payload.
    """
    adb("shell", "am", "start", "-n", ACTIVITY)


def matches(pattern):
    """Every buffered logcat line ending in `pattern`, oldest first.

    Anchored at both ends. `night=on` is nobody's prefix today, but
    `screen=thermal` was nobody's prefix either until `screen=thermal-clear`
    arrived, and that cost a review (MarkersTest says so).
    """
    rx = re.compile(r"(^|\s)%s$" % re.escape(pattern))
    return [line.strip() for line in adb("logcat", "-d", "-s", TAG).stdout.splitlines()
            if rx.search(line.rstrip())]


def preceded_by(line, pattern):
    """Is there a line ending in `pattern` earlier in the buffer than `line`?

    By position in the buffer, not by comparing the timestamps logcat prints:
    those carry no year, so a string comparison is chronological for eleven
    months and backwards across new year. The buffer is already in order.
    """
    buffered = [entry.strip() for entry
                in adb("logcat", "-d", "-s", TAG).stdout.splitlines()]
    if line not in buffered:
        return False
    rx = re.compile(r"(^|\s)%s$" % re.escape(pattern))
    return any(rx.search(entry) for entry in buffered[:buffered.index(line)])


def wait_for_marker(pattern, seconds, count=1):
    """Poll the buffer until `count` lines end in `pattern`, or give up."""
    deadline = time.monotonic() + seconds
    while True:
        found = matches(pattern)
        if len(found) >= count:
            return found[count - 1]
        if time.monotonic() >= deadline:
            return None
        time.sleep(2)


def report(fails):
    for line in fails:
        print("    FAIL %s" % line)
    print("FAIL: the night marker is not driven by the configured window" if fails
          else "PASS: the panel enters and leaves its night profile with the window")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None,
                    help="the config to take every setting but the window from")
    ap.add_argument("--wait", type=int, default=90, metavar="SECONDS",
                    help="how long to wait for each marker (default: 90)")
    args = ap.parse_args()

    devices = [line.split("\t")[0] for line in adb("devices").stdout.splitlines()[1:]
               if line.strip().endswith("\tdevice")]
    if len(devices) != 1:
        print("FAIL: expected exactly one device on adb, found %r" % devices)
        return 2

    # The same discovery order the server itself uses -- --config, then
    # $DESK_PANEL_CONFIG, then the script directory, where config.toml wins
    # over the older config.json. Naming one of the two here would have made
    # this acceptance die with a traceback on a machine set up the documented
    # way (T3.12), which is the shape of failure the rest of this file exists
    # to report cleanly.
    argv = ["--config", args.config] if args.config else []
    path = config_search_paths(argv, os.environ,
                               os.path.join(ROOT, "server"), os.path.exists)[0]
    try:
        base = load_config(path)
    except ConfigError as bad:
        print("FAIL: cannot read %s: %s" % (path, bad))
        return 2
    port = base.get("port", 8777)
    if not port_free(port):
        print("FAIL: something is already listening on %d. Stop it by PID -- "
              "`ss -ltnp 'sport = :%d'` -- and run this again." % (port, port))
        return 2

    # Only the day window is settled here. The night one has minutes to live
    # by design, and the baseline below takes two of them -- so it is
    # computed at the moment it is served, not at the moment the run starts.
    _, day, _ = windows(datetime.datetime.now())
    print("day window %s-%s" % day)

    server = Server(base, port)
    fails = []
    try:
        # --- the baseline, and the first question --------------------------
        #
        # A day window, the app on screen, and one refresh landed under it, so
        # that whatever the panel was doing before this run is over and
        # logged before the buffer is cleared.
        if not server.start(*day):
            print("FAIL: the server did not answer /ping in the day profile")
            return 2
        nudge()
        if wait_for_marker("state=online", args.wait) is None:
            print("FAIL: the phone never reported the server as up. Check the "
                  "firewall rule and the PC's address in .env.")
            return 2
        # **Two**, and the second one is not belt and braces. The app keeps
        # the night window across an offline stretch on purpose -- it is
        # configuration, not a measurement -- so a panel that was left in the
        # night profile by a previous run comes back online still in it, and
        # corrects itself on the first payload under the day window. That is
        # the feature working; it is also a `night=off` landing in the middle
        # of the quiet window below and reading as chatter. Waiting for a
        # second refresh puts the correction safely before the clear. It was
        # observed on the device rather than reasoned out:
        #
        #     19:40:11.336 data=ok
        #     19:40:11.340 night=off     <- last night's window, corrected
        if wait_for_marker("data=ok", CYCLE_SECONDS * 3, count=2) is None:
            print("FAIL: the phone never settled into the day profile")
            return 2

        adb("logcat", "-c")
        # An app logging the marker per refresh writes a line per cycle here;
        # a correct one writes none.
        if wait_for_marker("data=ok", CYCLE_SECONDS * 3, count=2) is None:
            print("FAIL: the phone stopped fetching during the quiet window")
            return 2
        chatter = matches("night=on") + matches("night=off")
        if chatter:
            fails.append("a steady panel logged %d night= lines across two "
                         "refreshes; the marker is a transition, not a "
                         "heartbeat: %r" % (len(chatter), chatter[:3]))

        # --- the rising edge ----------------------------------------------
        #
        # A restart, which may or may not be long enough for the phone to
        # notice. It does not matter here: a gap can only take the profile
        # off, never put it on, so night=on cannot be forged by one.
        adb("logcat", "-c")
        server.stop()
        night, _, night_seconds = windows(datetime.datetime.now())
        print("    night window %s-%s, ending in %ds" % (night + (night_seconds,)))
        expires_at = time.monotonic() + night_seconds
        if not server.start(*night):
            print("FAIL: the server did not answer /ping in the night profile")
            return 2
        nudge()
        line = wait_for_marker("night=on", args.wait)
        if line is None:
            fails.append("no night=on within %ds of a window that contains now"
                         % args.wait)
            # Nothing below can mean anything without this, and the falling
            # edge costs three minutes to not find out.
            return report(fails)
        print("    %s" % line)

        # Cleared again, and this is load-bearing rather than tidy: the
        # restart above may well have been long enough for the phone to go
        # offline and come back, and that state=offline would make the order
        # check below reject a perfectly good falling edge. From here the
        # buffer holds only what happened while the server sat still.
        adb("logcat", "-c")

        # --- the falling edge, with nothing moving but the clock -----------
        #
        # The server is left alone. The window ends, the next refresh finds
        # itself outside it, and the profile comes off -- which is the same
        # thing that happens at 07:00 every morning, and the only version of
        # this assertion that a restart cannot answer by accident.
        remaining = max(0, expires_at - time.monotonic())
        print("    waiting up to %ds for the window to end and one refresh "
              "to follow it" % (remaining + CYCLE_SECONDS * 2))
        line = wait_for_marker("night=off", remaining + CYCLE_SECONDS * 2)
        if line is None:
            fails.append("the window ended and the panel stayed in its night "
                         "profile")
        elif preceded_by(line, "state=offline"):
            # It has to be the window that did it. A state=offline before the
            # marker means the PC went away and took the profile with it,
            # which is correct behaviour and is not the answer being asked
            # for -- the first cut of this file passed on exactly that.
            fails.append("night=off came after a state=offline, so it was the "
                         "PC leaving and not the window ending")
        else:
            print("    %s" % line)
    finally:
        server.stop()

    return report(fails)


if __name__ == "__main__":
    sys.exit(main())
