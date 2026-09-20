"""Assert the blackout contract in a real browser. Exits non-zero on any failure.

    python e2e/layout/check_blackout.py [--theme NAME]

`check_layout.py` answers "does the panel fit". This answers "does the panel go
away, and come back with what it missed" -- the page's half of invariant 3
(ADR 0005) and of the thermal cutoff (T5.5, ADR 0012).

It exists because T6.7 moved that rule. The blackout used to be two class names
in the panel's own stylesheet; it is now one attribute on <html>, one rule in
core CSS, and a hold in js/app.js that keeps a payload out of a hidden DOM. Every
one of those is invisible in a screenshot and none of them had a command.

Nothing here reads a colour. `visibility` and the attribute are what the rule is
made of, and a theme is free to be any colour it likes underneath them.

Driven through check_layout.py's Marionette plumbing -- same Firefox, same
launcher -- so there is one browser harness in this repo and not two.
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

# Two payloads distinguishable by one glance at #quotes. The second also carries
# a theme, so the wake path is proved to run the theme switch and not just a
# re-render.
PAYLOAD_A = ("window.onData({quotes:[{symbol:'AAA',price:1,changePct:1}],fx:[],crypto:[],"
             "weather:{tempC:1,minC:0,maxC:2,code:0,city:'A'},"
             "battery:{level:50,tempC:30,charging:false},stale:false});")
PAYLOAD_B = ("window.onData({quotes:[{symbol:'BBB',price:2,changePct:2}],fx:[],crypto:[],"
             "weather:{tempC:9,minC:8,maxC:9,code:0,city:'B'},"
             "battery:{level:50,tempC:30,charging:false},stale:false,theme:'plain'});")

# More B3 rows than any card on any theme can show, so the panel is actually
# animating when the last check below blacks it out. Twelve rather than "a few
# more than fit" for the reason e2e/layout/overflow.js gives: one payload has to
# overflow neon's tall cards and plain's short columns both.
PAYLOAD_OVERFLOW = (
    "window.onData({quotes:Array.from({length:12},(_,i)=>"
    "({symbol:'Q'+i,price:10+i,changePct:i%3-1})),fx:[],crypto:[],"
    "weather:{tempC:1,minC:0,maxC:2,code:0,city:'A'},"
    "battery:{level:50,tempC:30,charging:false},stale:false});")


def check(m, fails):
    def js(src):
        return m.script(src)

    def quotes():
        return js("return document.getElementById('quotes').textContent;")

    def dark():
        return js("return document.documentElement.getAttribute('data-panel');") == "dark"

    def hidden():
        return js("return getComputedStyle(document.body).visibility;") == "hidden"

    # A clock before any payload. MainActivity reads #clock in onPageFinished to
    # log panel=rendered (T2.2, ADR 0009), and it reads it before the PC has said
    # anything -- so a page that only paints on data reports an empty clock.
    clock = js("return document.getElementById('clock').textContent;")
    if not clock or len(clock) != 8:
        fails.append("no clock at page load, before any payload: %r" % clock)

    # mock.js is live on a file: page and pushes its own payload every 3s, so the
    # assertions below have to land well inside that window. It is also why the
    # promise under test is "the latest payload is drawn on wake" rather than
    # "the one injected first" -- which is what app.js actually guarantees.
    js(PAYLOAD_A)
    if "AAA" not in quotes():
        fails.append("a payload delivered to a lit panel was not rendered")

    for name, go_dark, come_back in (
            ("thermal", "window.onThermal(true);", "window.onThermal(false);"),
            ("offline", "window.onPcState(false);", "window.onPcState(true);")):
        js(go_dark)
        if not dark():
            fails.append("%s: data-panel is not dark" % name)
        if not hidden():
            fails.append("%s: body is not hidden" % name)

        js(PAYLOAD_B if name == "thermal" else PAYLOAD_A)
        held = quotes()
        wanted = "BBB" if name == "thermal" else "AAA"
        if wanted in held:
            fails.append("%s: a payload was rendered into a dark panel: %r" % (name, held))

        js(come_back)
        back = quotes()
        if wanted not in back:
            fails.append("%s: the held payload was not drawn on wake: %r" % (name, back))
        if dark():
            fails.append("%s: data-panel is still set after coming back" % name)
        if hidden():
            fails.append("%s: body is still hidden after coming back" % name)
        woken_clock = js("return document.getElementById('clock').textContent;")
        if not woken_clock or len(woken_clock) != 8:
            fails.append("%s: clock is empty after coming back: %r" % (name, woken_clock))

        # Only the thermal payload carries a theme, and this has to be asserted
        # here rather than after the loop: the offline iteration delivers a
        # payload with no theme, which legitimately switches back to the
        # fallback. A check left until the end would be testing that instead.
        if name == "thermal":
            # A re-render alone would have left the panel in the old theme, so
            # this is what proves the wake runs the whole of onData's path.
            if js("""return document.querySelector("link[data-theme='plain']").media;""") != "all":
                fails.append("the held payload's theme switch did not happen on wake")
            if not js("return !!document.querySelector('.col-title');"):
                fails.append("the held payload's theme did not build its markup on wake")

    # Last, because it is the only check that has to wait: the clock stops while
    # nobody can see it, and starts again when somebody can.
    js("window.onThermal(true);")
    stopped = js("return document.getElementById('clock').textContent;")
    time.sleep(2.2)
    if js("return document.getElementById('clock').textContent;") != stopped:
        fails.append("the clock kept ticking into a dark panel")
    js("window.onThermal(false);")
    time.sleep(1.2)
    if js("return document.getElementById('clock').textContent;") == stopped:
        fails.append("the clock did not restart when the panel came back")

    # And nothing keeps moving behind the blackout.
    #
    # `visibility: hidden` stops the panel being drawn and does not stop a CSS
    # animation: it keeps ticking and its layer keeps being recomposited, on a
    # device that is either asleep on battery or being blanked for running hot.
    # T6.6 put the first animation on this page, so css/style.css pauses them --
    # and a rule about something invisible, in a state nobody looks at, is
    # exactly the kind that rots without a command.
    #
    # mock.js pushes a three-row payload every 3s on a file: page, and this block
    # cannot outrun it: a tick landing inside the dark window is *held* by
    # app.js and flushed on the way back, so it is the three-row payload that
    # gets drawn, data-scroll goes away, and a correct panel is reported as
    # having failed to resume its scroll. The checks above are written to
    # tolerate that (the payload under test is re-delivered each time); this one
    # cannot be, so the feed is stopped instead.
    #
    # Clearing every interval id is blunt and is the only handle available --
    # mock.js keeps its id to itself, deliberately, because nothing in
    # production has any business stopping the feed. It stops app.js's clock
    # too, which is why it happens here and not earlier: the clock checks above
    # are the only ones that need the timer, and they are done.
    js("for (let i = 1; i < 10000; i += 1) { clearInterval(i); }")

    js(PAYLOAD_OVERFLOW)
    if not js("return !!document.querySelector('#quotes[data-scroll]');"):
        fails.append("a card holding twelve rows did not declare data-scroll, so the "
                     "animation pause below would have been checked against nothing")
    else:
        # Found by what it does, not by what it is called: any element in the
        # card whose computed animation-name is not 'none'. A theme is free to
        # answer the overflow however it likes and to name its moving box
        # whatever it likes (docs/THEMING.md), so a class name here would be
        # this file knowing one theme's markup.
        moving = ("return (Array.from(document.querySelectorAll('#quotes *'))"
                  ".map((el) => getComputedStyle(el))"
                  ".filter((s) => s.animationName !== 'none')[0] || {})"
                  ".animationPlayState || 'none';")

        lit = js(moving)
        if lit != "running":
            fails.append("an overflowing card is not animating while the panel is lit: %r"
                         % lit)
        js("window.onThermal(true);")
        dark_state = js(moving)
        if dark_state != "paused":
            fails.append("the scroll kept running behind the blackout: %r" % dark_state)
        js("window.onThermal(false);")
        if js(moving) != "running":
            fails.append("the scroll did not resume when the panel came back")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", metavar="NAME",
                    help="start on this theme instead of the default")
    args = ap.parse_args()

    url = "file://" + os.path.abspath(PANEL)
    if args.theme:
        url += "?theme=" + urllib.parse.quote(args.theme)
    print("desk-panel blackout check -- %s" % url)

    profile = tempfile.mkdtemp(prefix="desk-panel-blackout-")
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
        # Nothing here reads a size, with one exception: the last check needs a
        # card to be actually overflowing, and how many rows overflow a card
        # depends on how tall the card is. In whatever window Firefox opened
        # with, twelve rows may well fit. The guard below catches that and says
        # so rather than passing quietly, but it is cheaper to measure the
        # viewport the panel is built for.
        cl.calibrate(m, *cl.VIEWPORT)
        time.sleep(cl.SETTLE_SECONDS)
        check(m, fails)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    for line in fails:
        print("    FAIL %s" % line)
    print("FAIL: the blackout contract is broken" if fails
          else "PASS: the panel goes dark, holds what arrives, and draws it on the way back")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
