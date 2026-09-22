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


# Stop the page's own timers before measuring.
#
# mock.js pushes a payload every 3s on a file: page and js/app.js repaints the
# clock every second, and the burn-in sweep below cannot outrun either: it sets
# the clock to a chosen minute and then takes two more round trips to measure,
# by which time app.js has put the real time -- and the real offset -- back.
# Clearing every interval id is blunt and is the only handle available; both
# other browser checks in this directory do the same thing for the same reason.
#
# It happens after the prelude, so the payload under measurement is already on
# screen, and the sweep re-delivers it at every offset anyway.
FREEZE = "for (let i = 1; i < 10000; i += 1) { clearInterval(i); }"

# The instant the page's clock is pinned to before anything is measured.
#
# Monday 23 February 2026, 12:00 local. The date is not arbitrary: it is the
# longest `toLocaleDateString('pt-BR', {weekday, year, month, day})` in 2026 --
# "segunda-feira, 23 de fevereiro de 2026", 38 characters -- and that string is
# what the stress pass draws into #date, because pt-BR is what the phone
# actually renders. Until this, that pass measured *today's* date, so the
# widest case was measured on the days it happened to be the widest case and
# the harness was a little different every morning.
#
# Midday, so the whole burn-in sweep below stays inside one day and #date does
# not change length underneath the measurements.
PINNED = (2026, 2, 23, 12, 0, 0)

# Pin it. Everything on this page that asks the time asks `new Date()`:
# js/app.js's clock, the burn-in shift through it, stress.js's pt-BR date. One
# of them -- the clock js/app.js repaints when a payload arrives -- runs inside
# the prelude, which is why setting the offset and then delivering a payload
# put the panel straight back where the wall clock said it should be, and why
# the first cut of this sweep measured seven positions and reported one.
#
# `Fixed.prototype = Real.prototype` matters: the pinned constructor has to
# produce real Dates, or `instanceof Date` and every method on them stops
# working for the page. The original is kept on window so a second call
# re-pins rather than wrapping the wrapper.
PIN_CLOCK = """
if (!window.__realDate) { window.__realDate = window.Date; }
const Real = window.__realDate;
const at = %d;
const Fixed = function (...args) { return args.length ? new Real(...args) : new Real(at); };
Fixed.now = function () { return at; };
Fixed.parse = Real.parse;
Fixed.UTC = Real.UTC;
Fixed.prototype = Real.prototype;
window.Date = Fixed;
return at;
"""

# Where the panel actually is, and what core asked for.
#
# `body.firstElementChild` is the theme's own outermost element, which is what
# css/style.css translates -- every theme has one and none of them is named
# here, the same rule the rest of this harness follows.
#
# A body with nothing in it returns nulls rather than throwing, and burn_in()
# turns that into a sentence. A theme that rendered nothing at all would
# otherwise take this harness down with a TypeError, and "the harness crashed"
# and "the panel is empty" are not the same report.
# `new window.Date()` and not `new Date()`: this script runs in Marionette's own
# sandbox, which has its own globals, so a bare `new Date()` here is built from
# the *harness's* Date and reads the wall clock however carefully the page's one
# has been pinned. That cost a debugging session -- seven positions measured,
# one offset reported, and the page perfectly correct throughout. It is the same
# cross-realm trap that made `instanceof Date` the wrong guard in offsetFor.
BURN_IN_AT = ("window.DeskPanel.tick(new window.Date());"
              "const s = document.documentElement.style;"
              "const el = document.body.firstElementChild;"
              "const r = el ? el.getBoundingClientRect() : null;"
              "return [parseFloat(s.getPropertyValue('--burn-in-x')) || 0,"
              "        parseFloat(s.getPropertyValue('--burn-in-y')) || 0,"
              "        r && r.left, r && r.top];")


def pinned_base_ms(m):
    """PINNED as epoch ms, read out of the page.

    In the page rather than in Python because offsetFor counts steps from the
    epoch, so the number that selects a position is a UTC instant -- and the
    page is the only thing here that knows what local time the panel is
    running in. Once per pass; the steps are added to it in Python.

    `window.__realDate` is the unpinned constructor, kept by PIN_CLOCK, so
    calling this a second time answers the same instant instead of one derived
    from the pin.
    """
    year, month, day, hour, minute, second = PINNED
    return m.script("return new (window.__realDate || Date)(%d, %d, %d, %d, %d, %d)"
                    ".getTime();" % (year, month - 1, day, hour, minute, second))


def run(url, passes, viewport, extra_css, shot_dir, shot_tag=""):
    """One browser, every pass. Returns {pass name: measurement}.

    Each pass is measured once per position in the burn-in cycle (T6.2), not
    once. The panel shifts a few pixels every four minutes so that one
    unchanging layout does not etch itself into an AMOLED, which means a
    harness that measured whatever the wall clock happened to be showing would
    check the worst position one run in seven -- and a card that only escapes
    the viewport at (-4,-3) would be a check that fails on a Tuesday. The sweep
    makes it a certainty instead.

    The first measurement of each pass is the one reported and screenshotted,
    and it is taken at a pinned clock rather than at the real one: the stress
    pass forces #clock to 23:59:59 precisely so its PNG is comparable between
    runs, and a shift that moved with the minute would have taken that away.

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

            m.script(FREEZE)
            schedule = m.script("return window.burnInSchedule();")
            base_ms = pinned_base_ms(m)
            step_ms = schedule["stepMinutes"] * 60 * 1000
            shifted = []
            for i in range(len(schedule["offsets"])):
                m.script(PIN_CLOCK % (base_ms + i * step_ms))
                x, y, left, top = m.script(BURN_IN_AT)
                # The prelude again, because the tick above repaints the clock
                # and the date -- and the stress pass exists partly to measure
                # the widest possible clock and a pt-BR date, which it writes
                # into the DOM itself. Without this the sweep would quietly
                # measure a narrower panel than the pass is named for. It is
                # safe to re-run only because the clock is pinned: the payload
                # it delivers repaints the clock, which is what used to put the
                # panel back at the wall clock's offset.
                if prelude:
                    m.script(read_js(prelude))
                result = m.script(measure)
                result["_outer_window"] = list(outer)
                result["_offset"] = [x, y]
                result["_anchor"] = [left, top]
                if i == 0:
                    results[name] = result
                    if shot_dir:
                        png = m.cmd("WebDriver:TakeScreenshot",
                                    {"full": False, "hash": False})["value"]
                        path = os.path.join(shot_dir,
                                            "layout-%s%s.png" % (shot_tag, name))
                        with open(path, "wb") as f:
                            f.write(base64.b64decode(png))
                        result["_screenshot"] = path
                else:
                    shifted.append(result)
            results[name]["_shifted"] = shifted
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


def burn_in(result, viewport, already):
    """The burn-in sweep's findings, which the single measurement cannot have.

    Two questions, and the first is the one that keeps the second honest:

      1. does core's offset actually reach the glass? The panel is moved by two
         custom properties on <html> and one rule in css/style.css, and if
         either goes the sweep below still runs, still measures seven times,
         and still reports a pass -- having measured one position seven times.
         So every position is checked against where the panel actually went.
      2. does the panel still fit at every position? This is the reason the
         sweep exists. Every offset is up and left, so the edges at risk are
         the top and the left: a card sitting 3px clear of the top of the
         viewport at (0,0) is over it at (-1,-4), and that is one position out
         of seven. Measured once, it is a layout bug that fails on a Tuesday.

    `already` is what the reported position failed on, so a fault present at
    every offset -- a card that does not fit at all -- is said once rather than
    seven times.
    """
    bad = []
    shifted = result.get("_shifted", [])
    if not shifted:
        return ["the burn-in cycle has one position in it, so this pass measured the "
                "panel where it always is and said nothing about where it goes "
                "(web/js/format.js, BURN_IN_OFFSETS)"]

    base_offset = result["_offset"]
    base_anchor = result["_anchor"]
    if base_anchor[0] is None:
        return ["the theme put nothing in the body, so there is nothing for the burn-in "
                "shift to move -- and every measurement in this pass was taken of an "
                "empty page"]
    moves = False
    for other in shifted:
        asked = [other["_offset"][i] - base_offset[i] for i in (0, 1)]
        # Before the empty-panel branch below, not after it. A theme that
        # rendered nothing would otherwise skip this and collect a second,
        # wrong finding on the way out -- "the panel never moves ... see
        # offsetFor" -- pointing the reader at the one part of this that was
        # working.
        if asked != [0, 0]:
            moves = True
        if other["_anchor"][0] is None:
            bad.append("the panel was empty at burn-in offset (%d,%d)"
                       % (other["_offset"][0], other["_offset"][1]))
            continue
        went = [other["_anchor"][i] - base_anchor[i] for i in (0, 1)]
        if any(abs(a - w) > 0.5 for a, w in zip(asked, went)):
            bad.append(
                "the burn-in shift is not reaching the panel: core moved from %s to %s, "
                "which is (%+d,%+d), and the panel moved (%+.1f,%+.1f). The rule that "
                "spends --burn-in-x/--burn-in-y is in web/css/style.css"
                % (tuple(base_offset), tuple(other["_offset"]),
                   asked[0], asked[1], went[0], went[1]))
        for line in failures(other, viewport):
            if line not in already and line not in bad:
                bad.append("at burn-in offset (%d,%d): %s"
                           % (other["_offset"][0], other["_offset"][1], line))

    if not moves:
        bad.append(
            "every position in the burn-in cycle is the same offset, so the panel "
            "never moves and nothing is protecting the display (web/js/format.js, "
            "offsetFor)")
    return bad


def report(name, result, bad):
    print("  pass %r  viewport %dx%d (outer window %dx%d)"
          % (name, result["viewport"][0], result["viewport"][1],
             result["_outer_window"][0], result["_outer_window"][1]))
    print("    document %dx%d" % tuple(result["doc"]))
    swept = [result] + result.get("_shifted", [])
    print("    burn-in  measured at %d of the cycle's positions: %s"
          % (len(swept),
             " ".join("(%d,%d)" % tuple(r["_offset"]) for r in swept)))
    for section, box in sorted(result["sections"].items()):
        # A section measure.js could not find is None, and the finding that says
        # so is already in `bad`. Printing it as "not in the DOM" rather than
        # indexing None keeps the report readable on exactly the run where the
        # panel is most broken -- this line used to raise TypeError and take the
        # harness down instead of reporting the fault it had just found.
        if box is None:
            print("    %-9s not in the DOM" % section)
            continue
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
    ap.add_argument("--lang", metavar="TAG",
                    help="measure the panel in this language instead of the default; "
                         "passed as ?lang=TAG, the same way --theme is (T6.11). Worth "
                         "running for every language that ships: the words are not the "
                         "same length, and the widest card title and the stale badge "
                         "share a strip")
    args = ap.parse_args()

    width, height = (int(n) for n in args.viewport.lower().split("x"))
    extra_css = None
    if args.extra_css:
        with open(args.extra_css) as f:
            extra_css = f.read()
    if args.screenshots:
        os.makedirs(args.screenshots, exist_ok=True)

    url = "file://" + os.path.abspath(PANEL)
    query = {}
    if args.theme:
        query["theme"] = args.theme
    if args.lang:
        query["lang"] = args.lang
    if query:
        url += "?" + urllib.parse.urlencode(query)

    # Four passes, and only the first is the ordinary case. A typical tick
    # never breaks a layout; the widest case does. mock.js already ships the
    # long symbol, the six-figure price, the sub-1 price and the zero change
    # (that is what those fixtures are for -- see web/js/mock.js). stress.js
    # adds what it cannot: the longest city, the longest label in format.js, a
    # negative temperature, the date as the panel's language renders it, and
    # the stale badge shown.
    #
    # unknown.js is the third and it measures one card: a WMO code with no
    # glyph, where the neon theme draws the *word* in the picture's slot. That
    # slot had never held text before T6.12, and the first cut of it squeezed
    # the 44px temperature into 91px and drew 118px of digits out of the card.
    # Cheap to keep and impossible to notice by eye -- 66 is freezing rain, on
    # a panel in Sao Paulo.
    #
    # overflow.js is the fourth, and it is the one pass that asserts something
    # must happen rather than that nothing must: more rows than any card can
    # show, and the cards have to say they are scrolling through them (T6.6).
    # The flag is what turns the pass from "nothing escaped" -- which a card
    # that silently eats rows passes trivially -- into a check of the feature.
    passes = [("served", None, False), ("stress", "stress.js", False),
              ("unknown", "unknown.js", False),
              ("overflow", "overflow.js", True)]

    print("desk-panel layout check -- %s" % url)
    results = run(url, [(name, prelude) for name, prelude, _ in passes],
                  (width, height), extra_css, args.screenshots,
                  shot_tag="".join("%s-" % v for v in
                                   (args.theme, args.lang) if v))

    broken = False
    for name, _, expect_scroll in passes:
        bad = failures(results[name], (width, height), expect_scroll)
        bad += burn_in(results[name], (width, height), bad)
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
