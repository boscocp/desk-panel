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
through -- the two bounds in the PC's config. So this walks them:

    day    -> night    and asserts night=on
    night  -> day      and asserts night=off

Both edges, because one of them is free to be wrong on its own: an
implementation that logged the marker on every refresh passes the first
assertion for ever, and one that never cleared its state passes the first and
fails the second.

The windows are computed from this machine's clock and are two hours wide, so
neither depends on which side of a minute boundary anything lands on. That
the *phone's* clock is the one being compared against is not something this
file can prove -- the two are minutes apart on the same desk -- and it is
covered where it can be: `NightWindowTest` drives the predicate off a
calendar it owns, and the payload carries two strings rather than a boolean
so that there is nothing else it could be comparing.

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

from server.server import load_config  # noqa: E402

SERVER = os.path.join(ROOT, "server", "server.py")
ACTIVITY = "dev.bosco.deskpanel/.MainActivity"
TAG = "DeskPanel"


def adb(*args, **kwargs):
    return subprocess.run(("adb",) + args, capture_output=True, text=True, **kwargs)


def hhmm(minute_of_day):
    minute_of_day %= 24 * 60
    return "%02d:%02d" % (minute_of_day // 60, minute_of_day % 60)


def windows(now):
    """(inside, outside): one window containing `now`, one three hours away."""
    minute = now.hour * 60 + now.minute
    return ((hhmm(minute - 60), hhmm(minute + 60)),
            (hhmm(minute + 180), hhmm(minute + 240)))


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


def wait_for_marker(pattern, seconds):
    """Poll the logcat buffer until a whole line matches, or give up.

    Anchored at both ends. `night=on` is nobody's prefix today, but
    `screen=thermal` was nobody's prefix either until `screen=thermal-clear`
    arrived, and that cost a review (MarkersTest says so).
    """
    rx = re.compile(r"(^|\s)%s$" % re.escape(pattern))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        out = adb("logcat", "-d", "-s", TAG).stdout
        for line in out.splitlines():
            if rx.search(line.rstrip()):
                return line.strip()
        time.sleep(2)
    return None


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

    base = load_config(args.config) if args.config else load_config(
        os.path.join(ROOT, "server", "config.json"))
    port = base.get("port", 8777)
    if not port_free(port):
        print("FAIL: something is already listening on %d. Stop it by PID -- "
              "`ss -ltnp 'sport = :%d'` -- and run this again." % (port, port))
        return 2

    inside, outside = windows(datetime.datetime.now())
    print("night window %s-%s, day window %s-%s" % (inside + outside))

    server = Server(base, port)
    fails = []
    try:
        # Day first, and the app on screen, so that the assertion below is an
        # edge and not the state the panel happened to already be in.
        if not server.start(*outside):
            print("FAIL: the server did not answer /ping in the day profile")
            return 2
        adb("shell", "am", "start", "-n", ACTIVITY)
        if wait_for_marker("state=online", args.wait) is None:
            print("FAIL: the phone never reported the server as up. Check the "
                  "firewall rule and the PC's address in .env.")
            return 2
        # One data cycle in the day profile, so night=off is genuinely where
        # the app starts from rather than where it has not got to yet.
        time.sleep(10)

        adb("logcat", "-c")

        server.stop()
        if not server.start(*inside):
            print("FAIL: the server did not answer /ping in the night profile")
            return 2
        nudge()
        line = wait_for_marker("night=on", args.wait)
        if line is None:
            fails.append("no night=on within %ds of a window that contains now"
                         % args.wait)
        else:
            print("    %s" % line)

        server.stop()
        if not server.start(*outside):
            print("FAIL: the server did not come back in the day profile")
            return 2
        nudge()
        line = wait_for_marker("night=off", args.wait)
        if line is None:
            fails.append("no night=off within %ds of a window that does not "
                         "contain now" % args.wait)
        else:
            print("    %s" % line)
    finally:
        server.stop()

    for line in fails:
        print("    FAIL %s" % line)
    print("FAIL: the night marker is not driven by the configured window" if fails
          else "PASS: the panel enters and leaves its night profile with the window")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
