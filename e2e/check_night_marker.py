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
through -- the two bounds in the PC's config. So the server is started once,
with a window that has not opened yet, and then **nothing restarts**: the
clock walks into the window and back out of it while the panel watches, which
is exactly what happens at 22:00 and at 07:00 every day. Three questions:

  1. **a steady panel outside the window logs nothing.** This is what the
     original acceptance was reaching for, and it is the assertion that fails
     an implementation logging the marker on every refresh -- the one shape
     that would pass questions 2 and 3 for ever.
  2. **the window opening turns the profile on.**
  3. **the window closing turns it off.**

**The restart-free shape is the third attempt and the reason is worth
keeping.** The obvious way to drive an edge is to restart the server into a
new config, and a restart is a gap in the server's answers -- a gap the probe
ladder notices is a logout as far as the phone is concerned. The panel goes
offline and the profile comes off with it, so `night=off` was logged by the
blip rather than by the window. Recorded on the device, two lines apart:

    19:36:22 night=on
    19:36:24 state=offline
    19:36:24 screen=sleep
    19:36:24 night=off      <- not the window. The PC leaving.

The second attempt drove the falling edge off the clock and left the rising
one behind a restart, which then had to reconnect a possibly-dozing phone
inside a window with minutes to live -- it passed with about seventy seconds
to spare, which is not a pass anybody should rely on. With the server never
gone there is no blip to have and no reconnect to race, and both edges are
guarded anyway: a `state=offline` before either marker fails the run.

The windows are computed from this machine's clock. That the *phone's* clock
is the one being compared against is not something this file can prove -- the
two are minutes apart on the same desk -- and it is covered where it can be:
`NightWindowTest` drives the predicate off a calendar it owns, and the
payload carries two strings rather than a boolean so that there is nothing
else it could be comparing.

Slow on purpose: nothing here can be hurried, because what is being waited
for is a clock. Budget about twelve minutes.

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


# When the window opens, and how long it stays open. Both are minutes from
# the moment the server starts, and the lead is what makes the whole run
# restart-free: the panel settles, the quiet window is measured, and only then
# does the clock walk into the window on its own.
#
# Six minutes of lead is generous on purpose. The panel has to come online
# after a stretch with no server, which can mean waking a dozing phone, and
# then two refreshes have to land -- and a lead that ran out early would look
# exactly like the feature being broken.
LEAD_SECONDS = 360
NIGHT_SECONDS = 180

# DataPoller's interval. Every wait here is written in cycles rather than in
# seconds, because what is being waited for is always "the next refresh".
CYCLE_SECONDS = 60


def window(now):
    """(start, end, opens_in, closes_in) for a window that has not opened yet.

    **Nothing restarts in this scenario, and that is the whole design.** The
    first two attempts drove the edges by restarting the server into a new
    config, and a restart is a gap in the server's answers: a gap the probe
    ladder notices is a logout as far as the phone is concerned, so the panel
    goes offline and the profile comes off with it. The falling edge was
    logged by that blip rather than by the window, visibly, on the device --
    `night=on`, then two seconds later `state=offline`, `screen=sleep`,
    `night=off`. The second attempt fixed the falling edge and left the rising
    one riding a reconnect that took most of the window's life.

    So the window is served once, by a server that never moves, and it simply
    opens and closes while the panel watches. Which is also exactly what
    happens at 22:00 and at 07:00 every day, and it is the only version of
    this that no blip can answer by accident: with the server never gone,
    there is no blip to have.

    Both bounds are modular, so both wrap midnight when the clock does. That
    is not a special case being dodged: 22:00 to 07:00 is the shipped window's
    own shape, and it gets exercised here for free once a night.
    """
    minute = now.hour * 60 + now.minute
    # Rounded up, because the payload's bounds have minute resolution: a
    # window "opening in 360 seconds" opens at the top of the minute at or
    # after that. The two counts back are what the waits are written against
    # -- deriving them from the constants would be up to a minute out,
    # depending only on which second of the minute the run started in.
    opens_at = -(-LEAD_SECONDS // 60)
    closes_at = opens_at + -(-NIGHT_SECONDS // 60)
    return (hhmm(minute + opens_at), hhmm(minute + closes_at),
            opens_at * 60 - now.second, closes_at * 60 - now.second)


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
    """Put the panel on screen, once, at the start.

    Whatever ran here last left the phone with no server to talk to, so it is
    offline, its screen is out and -- on battery -- it is probing on a
    fifteen-minute alarm (T5.6). Coming back from that unaided is T4.3's and
    T5.6's behaviour, they have their own acceptances, and waiting on them
    here would make this file's answer depend on theirs and take a quarter of
    an hour to get it.

    Called once and never again: nothing in this scenario restarts, so there
    is nothing else to come back from. It cannot put the panel into the night
    profile or out of it -- the only thing that does that is the window in the
    payload against the phone's own clock.
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

    start, end, opens_in, closes_in = window(datetime.datetime.now())
    print("night window %s-%s: opens in %ds, closes in %ds"
          % (start, end, opens_in, closes_in))

    server = Server(base, port)
    began = time.monotonic()
    fails = []
    try:
        # --- settle, and then ask the first question -----------------------
        #
        # The window has not opened yet, so this is the day profile with no
        # second config and no restart. Two refreshes rather than one: the app
        # keeps the night window across an offline stretch on purpose -- it is
        # configuration, not a measurement -- so a panel left in the night
        # profile by a previous run comes back online still in it and corrects
        # itself on the first payload. That correction is the feature working
        # and it is also a `night=off` that would read as chatter below. It
        # was observed on the device rather than reasoned out:
        #
        #     19:40:11.336 data=ok
        #     19:40:11.340 night=off     <- last night's window, corrected
        if not server.start(start, end):
            print("FAIL: the server did not answer /ping")
            return 2
        nudge()
        if wait_for_marker("state=online", args.wait) is None:
            print("FAIL: the phone never reported the server as up. Check the "
                  "firewall rule and the PC's address in .env.")
            return 2
        if wait_for_marker("data=ok", CYCLE_SECONDS * 3, count=2) is None:
            print("FAIL: the phone never settled into the day profile")
            return 2

        adb("logcat", "-c")
        # An app logging the marker per refresh writes a line per cycle here;
        # a correct one writes none.
        if wait_for_marker("data=ok", CYCLE_SECONDS * 3) is None:
            print("FAIL: the phone stopped fetching during the quiet window")
            return 2
        chatter = matches("night=on") + matches("night=off")
        if chatter:
            fails.append("a steady panel outside the window logged %d night= "
                         "lines; the marker is a transition, not a heartbeat: "
                         "%r" % (len(chatter), chatter[:3]))

        if time.monotonic() - began > opens_in:
            print("FAIL: settling took longer than the %ds lead, so the window "
                  "opened before the quiet check was over. Raise LEAD_SECONDS."
                  % opens_in)
            return 2

        # --- the window opens, and nothing else moves ----------------------
        adb("logcat", "-c")
        print("    waiting for the window to open")
        line = wait_for_marker("night=on",
                               opens_in - (time.monotonic() - began)
                               + CYCLE_SECONDS * 2)
        if line is None:
            fails.append("the window opened and the panel stayed in its day "
                         "profile")
            # Nothing below can mean anything without this, and waiting out
            # the rest of the window to not find out costs minutes.
            return report(fails)
        if preceded_by(line, "state=offline"):
            fails.append("night=on came after a state=offline, which this "
                         "scenario has no business producing at all")
        print("    %s" % line)

        # --- and closes ---------------------------------------------------
        adb("logcat", "-c")
        print("    waiting for the window to close")
        line = wait_for_marker("night=off",
                               closes_in - (time.monotonic() - began)
                               + CYCLE_SECONDS * 2)
        if line is None:
            fails.append("the window closed and the panel stayed in its night "
                         "profile")
        elif preceded_by(line, "state=offline"):
            # The failure the first two versions of this file shipped with: a
            # PC going away takes the profile off too, correctly, and that is
            # not the answer being asked for.
            fails.append("night=off came after a state=offline, so it was the "
                         "PC leaving and not the window closing")
        else:
            print("    %s" % line)
    finally:
        server.stop()

    return report(fails)


if __name__ == "__main__":
    sys.exit(main())
