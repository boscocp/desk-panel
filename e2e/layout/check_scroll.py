"""Assert the overflow scroll's contract in a real browser. Exits non-zero on any failure.

    python e2e/layout/check_scroll.py [--theme NAME]

`check_layout.py` answers "does the panel fit", and its overflow pass answers
"does a card that hides a row say so". Neither can answer the question T6.6
calls the whole of its difficulty: **does the scroll survive a refresh?**

`window.onData` replaces every row in every card about once a minute. A card
whose animation restarts on that never reaches the rows it is moving to reveal
-- it walks a little way down, jumps back to the top, and does it again for
ever. Nothing about that is visible in a screenshot, in a measurement, or in a
unit test: `format.js` is pure and cannot see an animation, and the layout
harness measures one frame.

So this drives the real thing over time. Four questions:

  1. does an overflowing card animate at all,
  2. does it actually move (a declaration is not a movement),
  3. does re-delivering the same rows leave it where it was,
  4. does a payload that fits take the scroll away again.

Question 3 is the one this file exists for. Questions 1 and 4 duplicate
`check_layout.py` cheaply and are worth having here anyway, because a failure of
3 would otherwise be indistinguishable from the card never having moved.

Driven through check_layout.py's Marionette plumbing -- same Firefox, same
launcher -- so there is one browser harness in this repo and not three.
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

# Six B3 rows: more than neon's tall card and more than plain's short column
# can show, and not many more. The count is a compromise with the clock. A pass
# takes four seconds a hidden row by design (T6.6), so twelve rows is nearly a
# minute of animation and the hold at the top of it alone is eight seconds --
# this file would spend that long asleep before it could see anything move.
# Three rows hidden is a seventeen-second pass, and it is visibly moving five
# seconds in. It is still built by a function rather than written out, because
# this file delivers it twice and the two deliveries have to be identical --
# that is the whole of question 3.
PAYLOAD = ("window.onData({quotes:Array.from({length:6},(_,i)=>"
           "({symbol:'Q'+i,price:10+i,changePct:i%%3-1})),fx:[],crypto:[],"
           "weather:{tempC:1,minC:0,maxC:2,code:0,city:'A'},"
           "battery:{level:50,tempC:30,charging:false},stale:false%s});")

# Three rows fit every card on every theme, so the scroll must go away.
FITS = ("window.onData({quotes:[{symbol:'A',price:1,changePct:1}],fx:[],crypto:[],"
        "weather:{tempC:1,minC:0,maxC:2,code:0,city:'A'},"
        "battery:{level:50,tempC:30,charging:false},stale:false%s});")

# The vertical component of the moving element's transform, or None when nothing
# in the card is animating. Read off the computed matrix rather than off the
# custom property: the property is what the theme asked for, and this has to be
# what the browser is actually drawing.
#
# The element is found by what it does -- a computed animation-name that is not
# 'none' -- and never by a class. A theme may answer the overflow however it
# likes and call its moving box whatever it likes (docs/THEMING.md); a selector
# here would make this file an assertion about neon's markup instead of about
# the contract.
#
# `[0]` was the only animating element in a card until T6.2, which gave a value
# that just changed a 280ms colour pulse. It is still the right one, and the
# reason is document order rather than luck: the box that moves a card's rows
# contains them, and an ancestor always precedes its descendants. A theme that
# animated a *sibling* placed above its scroller would break this -- and would
# be the first thing in either theme to do so.
OFFSET = """
const moving = Array.from(document.querySelectorAll('#quotes *'))
    .filter((el) => getComputedStyle(el).animationName !== 'none')[0];
if (!moving) {
    return null;
}
const t = getComputedStyle(moving).transform;
// 'none' before the first frame of the animation, and DOMMatrixReadOnly('none')
// throws in Chromium where Firefox returns the identity. Zero is the honest
// answer either way: an untransformed box is at offset zero.
return t && t !== 'none' ? new DOMMatrixReadOnly(t).m42 : 0;
"""

# How long one pass takes, in seconds, as the browser computed it. This file
# waits a fraction of it rather than a fixed number of seconds, because a fixed
# number is a fixed number against *these two themes' current taste*: the
# seconds per row is a custom property a theme sets (T6.6), and a theme that
# halved it would put the sample in the middle of the return pass, where the
# offset is legitimately shrinking -- and this file would report a working
# scroll as broken.
DURATION = """
const moving = Array.from(document.querySelectorAll('#quotes *'))
    .filter((el) => getComputedStyle(el).animationName !== 'none')[0];
return moving ? parseFloat(getComputedStyle(moving).animationDuration) : null;
"""


def check(m, fails, theme):
    def js(src):
        return m.script(src)

    payload = PAYLOAD % (",theme:'%s'" % theme if theme else "")
    fits = FITS % (",theme:'%s'" % theme if theme else "")

    # mock.js pushes its own three-row payload every 3s on a file: page, which
    # would take the scroll away in the middle of every question below. Clearing
    # every interval id is blunt and is the only handle available -- mock.js
    # keeps its id to itself, deliberately, because nothing in production has any
    # business stopping the feed. It stops app.js's clock too, which costs this
    # file nothing: no question here involves the time.
    js("for (let i = 1; i < 10000; i += 1) { clearInterval(i); }")

    js(payload)
    if not js("return !!document.querySelector('#quotes[data-scroll]');"):
        fails.append("six rows in a card that fits three did not declare data-scroll: "
                     "every question below would have been asked of a still panel")
        return

    first = js(OFFSET)
    if first is None:
        fails.append("#quotes declares data-scroll and nothing inside it is animating")
        return

    # Question 2, and the sample question 3 is measured against.
    #
    # Just under halfway through a pass: past the hold at the top -- 15% of the
    # cycle, seconds at these durations, and sampling inside it would call a
    # working card stationary -- and well short of the far end, where the card
    # turns around and starts back. Both ends matter. A fixed five seconds was
    # the first cut and it landed a couple of hundred milliseconds past the hold
    # on a slow run, where the card had moved 7px: enough to prove it moves, not
    # enough for any threshold to separate "carried across the refresh" from
    # "restarted at zero" while also tolerating the card still moving between
    # two samples taken milliseconds apart. Halfway in, the two outcomes are
    # ~50px and 0.
    duration = js(DURATION)
    wait = max(3.0, min(20.0, (duration or 17.0) * 0.45))
    time.sleep(wait)
    moved = js(OFFSET)
    if moved is None:
        # Nothing is animating any more. A sentence, not a TypeError: this is a
        # real outcome (a stray payload that fits, a theme that took the
        # attribute away) and an acceptance command that answered it with a
        # traceback would be read as the harness being broken.
        fails.append("the scroll stopped between two samples %.1fs apart" % wait)
        return
    if abs(moved - first) < 8.0:
        fails.append("the card declared a scroll and barely moved: %.2fpx after %.1fs of a "
                     "%.1fs pass (the keyframes' hold is meant to be a pause, not the whole "
                     "pass)" % (abs(moved - first), wait, duration or 0.0))
        return

    # Question 3, and the reason this file exists. The same six symbols
    # arrive again, exactly as they do from the PC once a minute. Every row
    # element in the card is replaced. The offset must not care.
    js(payload)
    after = js(OFFSET)
    if after is None:
        fails.append("a refresh with the same rows stopped the scroll entirely")
    elif abs(after) < abs(moved) * 0.5:
        # Toward zero, because that is what a restart looks like: the animation
        # begins again at translateY(0) and holds there for the length of the
        # pause. Proportional rather than an absolute tolerance -- the card is
        # genuinely still moving between the two samples, and it is moving
        # *away* from zero, so the only way to land under half of the previous
        # offset is to have gone back to the top.
        fails.append(
            "a refresh that changed no rows reset the scroll: %.2fpx before, %.2fpx "
            "after. The animated element is being replaced by render(), or its "
            "declaration is being rewritten with different values -- see T6.6 step 4 "
            "and docs/THEMING.md." % (moved, after))

    # Question 4. Fewer rows than the card holds: no attribute, and nothing left
    # transformed. A card frozen at the offset it happened to reach, with its
    # rows scrolled half out of sight and nothing moving them back, is the worst
    # available outcome here.
    js(fits)
    if js("return !!document.querySelector('#quotes[data-scroll]');"):
        fails.append("a card that fits its rows kept data-scroll")
    resting = js("""
        // `transform` is the string 'none' on an untransformed element, and
        // every element in this card is untransformed by the time this runs.
        // Firefox hands DOMMatrixReadOnly('none') back as the identity matrix
        // and Chromium throws SyntaxError on it -- so the filter is what keeps
        // this file from being quietly Firefox-only, in a repo whose real
        // target is a Chromium WebView.
        return Math.max(0, ...Array.from(document.querySelectorAll('#quotes *'))
            .map((el) => getComputedStyle(el).transform)
            .filter((t) => t && t !== 'none')
            .map((t) => Math.abs(new DOMMatrixReadOnly(t).m42)));
    """)
    if resting > 0.5:
        fails.append("a card that fits its rows is still translated by %.2fpx: its rows "
                     "are scrolled out of sight with nothing moving them back" % resting)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", metavar="NAME",
                    help="measure this theme instead of the default")
    args = ap.parse_args()

    url = "file://" + os.path.abspath(PANEL)
    if args.theme:
        url += "?theme=" + urllib.parse.quote(args.theme)
    print("desk-panel scroll check -- %s" % url)

    profile = tempfile.mkdtemp(prefix="desk-panel-scroll-")
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
        # The phone's real viewport, and not optional here. Every number in this
        # file -- how many rows fit a card, how many are therefore hidden, how
        # long a pass takes and how far it travels -- comes out of the card's
        # height. Measured in whatever window Firefox opened with, six rows fit
        # a card that holds three on the device, nothing scrolls, and the check
        # reports the feature missing. calibrate() refuses to proceed if it
        # cannot converge, which is what makes that a failure to run rather than
        # a failure to pass (see check_layout.py).
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
        print("    FAIL %s" % line)
    print("FAIL: the overflow scroll is broken" if fails
          else "PASS: an overflowing card moves, survives a refresh, and stops when it fits")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except cl.MarionetteError as exc:
        # Exit 2, like check_layout.py: "the harness could not run" is a
        # different answer from "the scroll is broken", and an acceptance
        # command that confused the two would fail a correct panel on a machine
        # with no Firefox.
        print("harness error: %s" % exc, file=sys.stderr)
        sys.exit(2)
