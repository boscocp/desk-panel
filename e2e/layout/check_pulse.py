"""Assert that a value only pulses when it changed. Exits non-zero on any failure.

    python e2e/layout/check_pulse.py [--theme NAME]

T6.2 step 2: a value that changed lifts toward a brighter accent for 280ms and
comes back. The look of it is taste and belongs in a manual check -- what is
not taste is *when* it happens, and there is one way to get that wrong that
nobody would ever see on this desk.

`window.onData` is a full replacement: every row in every card is rebuilt once
a minute whether or not a single number moved. A theme that hung the pulse on
"a payload arrived" rather than on "this value is not what it was" would look
perfect here, where the browser fixture jitters every price every three
seconds -- and on the device, with the upstream down and the server serving
last-good values, it would flash every number on the panel once a minute while
STALE sat in the corner saying the opposite. That is the case this file exists
for, and it is three payloads long.

  1. a freshly mounted panel does not pulse, however different its values are
     from what was on screen a moment ago: the first sight of a value is not
     news about it. This is a real path and not a contrivance -- core empties
     the root whenever the theme changes, which is a key in a file on the PC
     (T6.7), and it is the same state the page is in at load.
  2. a value that changed does pulse, and only that value,
  3. the identical payload again pulses nothing. This is the stale case.

Plus one number, because the task file gives one: the pass must be over inside
~300ms. A pulse long enough to watch is a pulse you end up watching, on
something that sits beside you all day.

A theme is free not to do any of this (docs/THEMING.md), and `plain`
deliberately does not -- it has no glow and no accent either. So this is a
check of a theme rather than of the panel's contract, and it is run for the
themes that pulse and not for the ones that do not. There is no skip: a theme
where nothing pulses fails question 2, which is the only way this file can
still fail when the feature is deleted. `--theme` is there for the next theme
that wants it, not so that `plain` can be made to pass.

Driven through check_layout.py's Marionette plumbing -- same Firefox, same
launcher -- so a fourth browser check is not a fourth browser harness.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import check_layout as cl  # noqa: E402  - needs HERE on the path first

PANEL = os.path.join(HERE, "..", "..", "web", "index.html")

# The ceiling the task file names, in milliseconds. Anything longer "becomes
# tiring on a panel you sit next to all day"; a little headroom over it, because
# this is a check against a theme having quietly turned a flash into a fade.
MAX_PULSE_MS = 400.0

# One row per card, so no card can overflow and no scroll animation can be
# mistaken for a pulse. `price` is the only thing that moves between A and B --
# same symbol, same change, same weather, same battery -- so exactly one value
# on the panel has news in it.
PAYLOAD = ("window.onData({quotes:[{symbol:'AAA',price:%s,changePct:1}],"
           "fx:[{pair:'USD/BRL',rate:5.12,changePct:-0.3}],"
           "crypto:[{symbol:'BTC',price:341200,changePct:2.8}],"
           "weather:{tempC:21,minC:18,maxC:27,code:0,city:'A'},"
           "battery:{level:50,tempC:30,charging:false},stale:false%s});")

# Any packaged theme that is not the one under test. Delivering a payload that
# names it is how this file empties the panel: host.js clears the root on a
# theme change, which is the one way from outside the page to reach the state
# a fresh page load is in. mock.js renders the moment the page opens, so there
# is no other window in which the panel has never shown anything.
FOIL_THEME = "plain"

# Everything on the panel that is running an animation, by what it does and
# never by a class: a theme may call its pulsing element whatever it likes, and
# a selector here would make this file an assertion about neon's markup.
#
# The text is carried back with it so a failure says *which* value pulsed,
# which is the difference between a report and a puzzle.
PULSING = """
return Array.from(document.querySelectorAll('body *'))
    .filter((el) => getComputedStyle(el).animationName !== 'none')
    .map((el) => ({
        text: (el.textContent || '').trim().slice(0, 24),
        ms: parseFloat(getComputedStyle(el).animationDuration) * 1000,
    }));
"""


def check(m, fails, theme):
    def js(src):
        return m.script(src)

    def payload(price):
        return PAYLOAD % (price, ",theme:'%s'" % theme if theme else "")

    # mock.js pushes its own payload every 3s on a file: page, which would
    # rewrite every row in the middle of the three questions below -- and its
    # prices jitter, so it would pulse things this file did not ask to change.
    # Clearing every interval id is blunt and is the only handle available;
    # every browser check in this directory does the same thing for the same
    # reason. It stops js/app.js's clock too, which costs nothing here.
    js("for (let i = 1; i < 10000; i += 1) { clearInterval(i); }")

    # 1. Away to another theme and back, which empties the root, and back with
    #    every value different from the one it left. A fresh panel has nothing
    #    to compare against and must pulse nothing at all.
    js(PAYLOAD % ("10.00", ",theme:'%s'" % FOIL_THEME))
    js(payload("11.00"))
    first = js(PULSING)
    if first:
        fails.append("a freshly mounted panel pulsed %s. The first sight of a number is "
                     "not news about it, and a panel that pulses a new row flashes "
                     "every row on every theme switch and every page load."
                     % ", ".join(repr(p["text"]) for p in first))

    # 2. The same rows, one different price. Exactly one value has changed.
    js(payload("12.00"))
    moved = js(PULSING)
    texts = [p["text"] for p in moved]
    if not moved:
        fails.append(
            "nothing pulsed when a price changed. Either this theme does not pulse -- "
            "in which case questions 1 and 3 above and below proved nothing and this "
            "file should be skipped for it, as docs/THEMING.md allows -- or the value "
            "that changed is not being noticed.")
        return
    if not any("12.00" in t for t in texts):
        fails.append("the price that changed did not pulse; these did: %s" % texts)
    if len(moved) > 1:
        fails.append(
            "a payload with one changed value pulsed %d things: %s. Everything else on "
            "the panel is identical to the payload before it, so whatever pulsed is "
            "keying on the refresh and not on the value." % (len(moved), texts))
    for p in moved:
        if not p["ms"] or p["ms"] > MAX_PULSE_MS:
            fails.append(
                "%r pulses for %.0fms. The task file's ceiling is ~300ms: longer than "
                "that stops being a flash you notice and becomes a movement you watch, "
                "on a panel that is beside you all day." % (p["text"], p["ms"]))

    # 3. The stale case, and the reason this file exists. Byte-identical to the
    #    payload before it, which is what the server sends while an upstream is
    #    down and it is serving last-good values.
    js(payload("12.00"))
    again = js(PULSING)
    if again:
        fails.append(
            "a payload that changed nothing pulsed %s. This is what the panel looks "
            "like with the upstream down: every number flashing once a minute while "
            "STALE sits in the corner saying nothing has moved."
            % ", ".join(repr(p["text"]) for p in again))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", metavar="NAME",
                    help="check this theme instead of the default")
    args = ap.parse_args()

    url = "file://" + os.path.abspath(PANEL)
    if args.theme:
        url += "?theme=" + urllib.parse.quote(args.theme)
    print("desk-panel pulse check -- %s" % url)

    profile = tempfile.mkdtemp(prefix="desk-panel-pulse-")
    proc = cl.launch(profile)
    sock = cl.connect()
    if sock is None:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        return 2

    fails = []
    try:
        m = cl.Marionette(sock)
        m.read()  # server handshake
        m.cmd("WebDriver:NewSession", {"capabilities": {}})
        m.cmd("WebDriver:Navigate", {"url": url})
        # The phone's real viewport. Nothing here is a measurement, but a card
        # that overflows in a window this file did not choose would start the
        # scroll animation, and question 2 counts animating elements.
        cl.calibrate(m, *cl.VIEWPORT)
        time.sleep(cl.SETTLE_SECONDS)
        check(m, fails, args.theme)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    for line in fails:
        print("  FAIL %s" % line)
    print("FAIL: a value pulsed when it should not have, or did not when it should"
          if fails else
          "PASS: only a value that changed pulses, and it is over in a moment")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except cl.MarionetteError as exc:
        print("harness error: %s" % exc, file=sys.stderr)
        sys.exit(2)
