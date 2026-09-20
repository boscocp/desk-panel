#!/usr/bin/env python3
"""Measure the panel at the phone's real viewport and fail if anything is wrong with it.

Written for T6.1, kept for T6.2/T6.3/T6.4: every one of them changes sizes, and
a size change is exactly what pushes the fifth card off the bottom of a 392 CSS
px tall screen. Standard library only, like server/ -- no npm, no driver binary,
no Selenium.

Exit codes, so this can be an acceptance command:
    0  every section fits and nothing overlaps, in every pass
    1  something clipped, overflowed or was drawn on top of something else --
       the report says what
    2  the harness could not run (no firefox, no marionette, no calibration)

See README.md in this directory.
"""

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(os.path.dirname(HERE), os.pardir, "web", "index.html")

# The Redmi Note 10's landscape WebView viewport, in CSS px.
#
# Do not tidy this into a rounder number. The panel is 2400x1080 physical at
# 440dpi, which is 872x392 in CSS px -- and the width is 872 rather than the 839
# you get by default because MainActivity sets
# LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES and claims the camera cutout strip
# (T2.3). Measured on the device, not derived on paper. If the cutout mode ever
# changes, this number changes with it and the layout has to be re-measured.
VIEWPORT = (872, 392)

# Marionette's default is 2828. Using a different port keeps this off any
# Firefox the developer already has open.
PORT = 2829

# Firefox must come up, load the page and let mock.js tick before measuring.
SETTLE_SECONDS = 1.5


class MarionetteError(RuntimeError):
    pass


class Marionette:
    """The few Marionette commands this needs. Messages are `len:JSON`."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        self.seq = 0

    def read(self):
        while b":" not in self.buf:
            self.buf += self.sock.recv(65536)
        length, _, rest = self.buf.partition(b":")
        need = int(length)
        while len(rest) < need:
            rest += self.sock.recv(65536)
        self.buf = rest[need:]
        return json.loads(rest[:need])

    def cmd(self, name, params=None):
        self.seq += 1
        body = json.dumps([0, self.seq, name, params or {}]).encode()
        self.sock.sendall(b"%d:%s" % (len(body), body))
        msg = self.read()
        if msg[2] is not None:
            raise MarionetteError("%s -> %s" % (name, msg[2]))
        return msg[3]

    def script(self, source):
        return self.cmd("WebDriver:ExecuteScript", {"script": source, "args": []})["value"]


def calibrate(m, width, height):
    """Make the LAYOUT viewport exactly width x height, and prove it.

    THE TRAP THIS FUNCTION EXISTS FOR. SetWindowRect -- and Firefox's
    --window-size, and Chrome's equivalent -- size the OUTER window, not the
    layout viewport. Asking for 872x392 on the machine this was written on
    produced an innerHeight of 306: 86px short. Every measurement taken against
    that is wrong in the reassuring direction, because a page that fits a
    viewport 86px shorter than the real one trivially fits the real one. The
    check would have passed on a layout that clips on the phone.

    So: ask, read innerWidth/innerHeight back, correct by the difference, repeat.
    Then refuse to measure at all if it did not converge -- a harness that
    silently measures the wrong viewport is worse than no harness.
    """
    outer_w, outer_h = width, height
    inner = (None, None)
    for _ in range(8):
        m.cmd("WebDriver:SetWindowRect",
              {"width": outer_w, "height": outer_h, "x": 0, "y": 0})
        inner = tuple(m.script("return [window.innerWidth, window.innerHeight];"))
        if inner == (width, height):
            return outer_w, outer_h
        outer_w += width - inner[0]
        outer_h += height - inner[1]
    raise MarionetteError(
        "viewport did not converge on %dx%d (got %sx%s). Refusing to measure: "
        "every number would be wrong in the direction that looks like a pass."
        % (width, height, inner[0], inner[1]))


def launch(profile):
    with open(os.path.join(profile, "user.js"), "w") as f:
        f.write('user_pref("marionette.port", %d);\n' % PORT)
        f.write('user_pref("browser.shell.checkDefaultBrowser", false);\n')
    try:
        return subprocess.Popen(
            ["firefox", "--headless", "--marionette", "--no-remote",
             "--profile", profile, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit("firefox not found on PATH. This harness drives Firefox over "
                 "Marionette; see e2e/layout/README.md.")


def connect():
    for _ in range(120):
        try:
            return socket.create_connection(("127.0.0.1", PORT), timeout=60)
        except OSError:
            time.sleep(0.5)
    return None


def run(url, passes, viewport, extra_css, shot_dir, shot_tag=""):
    """One browser, every pass. Returns {pass name: measurement}.

    `shot_tag` goes in the screenshot filename. Without it a --theme run
    overwrites the default run's PNGs in the same directory, which is exactly
    the comparison the flag exists to make: T6.7's claim that the neon render
    survived the move is an md5 of two files written by two runs.
    """
    profile = tempfile.mkdtemp(prefix="desk-panel-layout-")
    proc = launch(profile)
    sock = connect()
    if sock is None:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        sys.exit(2)

    results = {}
    try:
        m = Marionette(sock)
        m.read()  # server handshake
        m.cmd("WebDriver:NewSession", {"capabilities": {}})
        measure = read_js("measure.js")
        for name, prelude in passes:
            m.cmd("WebDriver:Navigate", {"url": url})
            outer = calibrate(m, *viewport)
            if extra_css:
                m.script(
                    "const s = document.createElement('style');"
                    "s.textContent = arguments === undefined ? '' : %s;"
                    "document.head.appendChild(s); return true;" % json.dumps(extra_css))
            time.sleep(SETTLE_SECONDS)
            if prelude:
                m.script(read_js(prelude))
            result = m.script(measure)
            result["_outer_window"] = list(outer)
            results[name] = result
            if shot_dir:
                png = m.cmd("WebDriver:TakeScreenshot", {"full": False, "hash": False})["value"]
                path = os.path.join(shot_dir, "layout-%s%s.png" % (shot_tag, name))
                with open(path, "wb") as f:
                    f.write(base64.b64decode(png))
                result["_screenshot"] = path
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return results


def read_js(name):
    with open(os.path.join(HERE, name)) as f:
        return f.read()


def failures(result, viewport, expect_scroll=False):
    """Everything wrong with one pass, as a list of human sentences."""
    bad = []
    width, height = viewport
    if result["viewport"] != [width, height]:
        bad.append("viewport is %s, expected %s" % (result["viewport"], [width, height]))

    # A section holding nothing always fits. Before T6.1 the panel looked fine
    # on the device for exactly this reason: the cards were empty outlines,
    # because mock.js only runs under file: and the APK serves over https. Guard
    # it, or this harness passes loudest when it is measuring nothing.
    if result["emptySections"]:
        bad.append("sections rendered empty, so this pass measured nothing: %s. "
                   "Is mock.js loading? It only runs under file://."
                   % ", ".join(result["emptySections"]))

    doc_w, doc_h = result["doc"]
    if doc_h > height:
        bad.append("page is %dpx tall in a %dpx viewport: it scrolls, so %dpx is off screen"
                   % (doc_h, height, doc_h - height))
    if doc_w > width:
        bad.append("page is %dpx wide in a %dpx viewport" % (doc_w, width))
    for item in result["outsideViewport"]:
        bad.append("outside the viewport: %s" % item)
    for item in result["clippedContent"]:
        bad.append("clips its own content: %s" % item)
    # Everything can fit and still be unreadable, if some of it is underneath
    # the rest. This is the only check here that compares two sections against
    # each other rather than against the viewport -- see measure.js, and T5.4,
    # which is the bug that earned it.
    for item in result.get("overlaps", []):
        bad.append("drawn on top of something: %s" % item)
    # T6.6 step 2: a card that scrolls with two rows in it is motion for its own
    # sake, on a panel that sits in someone's peripheral vision all day. The
    # clock and the weather card are the ones this is really guarding -- neither
    # overflows, and neither may acquire movement from a rule meant for a list.
    for item in result.get("pointlessMotion", []):
        bad.append("moves for nothing: %s" % item)

    # The inverse assertion: this harness's only statement about what must
    # happen, as opposed to what must not. (check_scroll.py beside it makes the
    # stronger one, over time; this is the cheap frame-by-frame half.)
    #
    # Every check above says "nothing escaped". A card that swallows its extra
    # rows passes all of them -- that is exactly what the panel did before
    # T6.6, and why the sixth ticker was invisible rather than broken. So the
    # overflow pass, whose fixture holds more rows than any card can show,
    # requires the opposite: the cards must say they are scrolling. If the
    # scroll ever regresses to a plain clip, `clippedContent` catches it; if it
    # regresses to no overflow at all -- a fixture nobody topped up after the
    # cards grew -- this catches that instead, and the two together are what
    # stop this pass quietly measuring nothing.
    if expect_scroll and not result.get("scrolling"):
        bad.append(
            "no section is scrolling, so this pass proved nothing: either the "
            "overflow scroll regressed, or the fixture no longer overflows the "
            "cards it was written for (e2e/layout/overflow.js)")
    return bad


def report(name, result, bad):
    print("  pass %r  viewport %dx%d (outer window %dx%d)"
          % (name, result["viewport"][0], result["viewport"][1],
             result["_outer_window"][0], result["_outer_window"][1]))
    print("    document %dx%d" % tuple(result["doc"]))
    for section, box in sorted(result["sections"].items()):
        print("    %-9s x %4d-%-4d y %4d-%-4d  %s"
              % (section, box["left"], box["right"], box["top"], box["bottom"],
                 box["text"][:46]))
    for item in result.get("scrolling", []):
        print("    scrolls %s" % item)
    if result.get("_screenshot"):
        print("    screenshot %s" % result["_screenshot"])
    if bad:
        for line in bad:
            print("    FAIL %s" % line)
    else:
        print("    ok: nothing outside the viewport, nothing clipped, nothing overlapping")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--viewport", default="%dx%d" % VIEWPORT,
                    help="WxH in CSS px (default: the phone's real %dx%d)" % VIEWPORT)
    ap.add_argument("--extra-css", metavar="FILE",
                    help="inject this CSS before measuring, to try a size change "
                         "without editing web/")
    ap.add_argument("--screenshots", metavar="DIR",
                    help="also save a PNG per pass")
    ap.add_argument("--theme", metavar="NAME",
                    help="measure web/themes/NAME instead of the default; passed to the "
                         "page as ?theme=NAME, which mock.js and stress.js put in the "
                         "payload exactly as the server's config key does (T6.7)")
    args = ap.parse_args()

    width, height = (int(n) for n in args.viewport.lower().split("x"))
    extra_css = None
    if args.extra_css:
        with open(args.extra_css) as f:
            extra_css = f.read()
    if args.screenshots:
        os.makedirs(args.screenshots, exist_ok=True)

    url = "file://" + os.path.abspath(PANEL)
    if args.theme:
        url += "?theme=" + urllib.parse.quote(args.theme)

    # Three passes, and only the first is the ordinary case. A typical tick
    # never breaks a layout; the widest case does. mock.js already ships the
    # long symbol, the six-figure price, the sub-1 price and the zero change
    # (that is what those fixtures are for -- see web/js/mock.js). stress.js
    # adds what it cannot: the longest city, the longest label in format.js, a
    # negative temperature, a pt-BR date as the device actually renders it, and
    # the STALE badge shown.
    #
    # overflow.js is the third, and it is the one pass that asserts something
    # must happen rather than that nothing must: more rows than any card can
    # show, and the cards have to say they are scrolling through them (T6.6).
    # The flag is what turns the pass from "nothing escaped" -- which a card
    # that silently eats rows passes trivially -- into a check of the feature.
    passes = [("served", None, False), ("stress", "stress.js", False),
              ("overflow", "overflow.js", True)]

    print("desk-panel layout check -- %s" % url)
    results = run(url, [(name, prelude) for name, prelude, _ in passes],
                  (width, height), extra_css, args.screenshots,
                  shot_tag=("%s-" % args.theme) if args.theme else "")

    broken = False
    for name, _, expect_scroll in passes:
        bad = failures(results[name], (width, height), expect_scroll)
        report(name, results[name], bad)
        broken = broken or bool(bad)

    # "is wrong at", not "does not fit": since T5.4 a pass can fail on an
    # overlap, where everything fits and some of it is underneath the rest.
    print("FAIL: the layout is wrong at %dx%d" % (width, height) if broken
          else "PASS: every section fits %dx%d and nothing overlaps, in every pass"
               % (width, height))
    return 1 if broken else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MarionetteError as exc:
        print("harness error: %s" % exc, file=sys.stderr)
        sys.exit(2)
