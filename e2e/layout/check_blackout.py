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
