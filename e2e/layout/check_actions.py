"""Assert the shortcut-button contract in a real browser. Exits non-zero on any failure.

    python e2e/layout/check_actions.py [--theme NAME]

`check_layout.py` answers "does the panel fit" and `check_blackout.py` answers
"does it go away and come back". This answers "does pressing a button do the
right thing, and the right nothing" -- T8.2's contract, which is four rules and
none of them visible in a screenshot:

  1. the buttons drawn are the ones the PC enabled, in that order, and nothing
     is drawn for an id this build has no word for;
  2. the target is at least 56x56, because the two sit next to each other and
     the failure that size prevents is muting the microphone when you meant the
     speakers;
  3. a press reaches the bridge with the id and nothing else -- never a URL;
  4. **a press while the PC is away sends nothing.** There is no queue. A
     queued action firing on reconnect would mute the PC minutes after somebody
     pressed a button they could not see.

The bridge is replaced here with one that records what it was handed, so this
runs with no phone, no server and no PC. What it cannot prove is that the id
reaches the PC -- that is the `action=` logcat marker and lives in T8.2's
device check.

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

# The bridge MainActivity installs, replaced by one that records. `sent` is what
# the page handed over, and nothing else: an id, and no URL anywhere near it.
#
# It does not answer by itself. Each case below decides whether that press
# succeeded and calls window.onActionResult, which is what the real Java does
# from its own thread -- so the page's handling of a result it did not produce
# synchronously is what is under test rather than a convenient stub.
RECORDER = """
window.__sent = [];
window.__actions = {
    invoke: function (id) {
        window.__sent.push(id);
        return window.__accept !== false;
    }
};
window.__accept = true;
"""


def payload(actions, theme=None, language=None):
    """One payload with an `actions` list. Everything else is the minimum."""
    extra = ""
    if theme:
        extra += ",theme:'%s'" % theme
    if language:
        extra += ",language:'%s'" % language
    return ("window.onData({quotes:[{symbol:'AAA',price:1,changePct:1}],fx:[],crypto:[],"
            "weather:{tempC:1,minC:0,maxC:2,code:0,city:'A'},"
            "battery:{level:50,tempC:30,charging:false},stale:false,"
            "actions:[%s]%s});"
            % (",".join("'%s'" % a for a in actions), extra))


def check(m, fails, theme):
    def js(src):
        return m.script(src)

    # Every payload below carries the theme under test. Without it,
    # `payload.theme` is undefined, host.useTheme falls back to neon, and the
    # panel silently switches out from under a --theme plain run -- which is
    # how this file first failed on plain and passed on neon.
    def deliver(actions):
        return js(payload(actions, theme=theme))

    def ids():
        return js("return Array.from(document.querySelectorAll('#shortcuts .shortcut'))"
                  ".map(function (b) { return b.dataset.action; });") or []

    def sent():
        return js("return window.__sent.slice();") or []

    def press(action_id):
        # A real click, dispatched the way a finger does it, so the theme's own
        # listener is what runs. Calling the handler directly would test this
        # file's idea of the theme instead of the theme.
        return js("var b = document.querySelector('#shortcuts [data-action=\"%s\"]');"
                  "if (!b) { return false; } b.click(); return true;" % action_id)

    js(RECORDER)

    # --- 1. which buttons exist is the PC's decision ------------------------
    deliver(["mute-mic", "mute-audio"])
    if ids() != ["mute-mic", "mute-audio"]:
        fails.append("the buttons are not the ids the PC sent, in order: %r" % ids())

    deliver(["mute-audio", "mute-everything"])
    drawn = ids()
    if drawn != ["mute-audio"]:
        fails.append("an id this build has no word for was drawn: %r" % drawn)

    deliver([])
    if ids():
        fails.append("buttons were drawn for a PC that enabled none: %r" % ids())

    # A panel whose owner enabled nothing is the default, and the strip must be
    # empty rather than holding a placeholder that takes the space.
    if (js("return document.getElementById('shortcuts').textContent.trim();") or "") != "":
        fails.append("the empty strip is not empty")

    # --- 2. the target size -------------------------------------------------
    deliver(["mute-audio", "mute-mic"])
    boxes = js("return Array.from(document.querySelectorAll('#shortcuts .shortcut'))"
               ".map(function (b) { var r = b.getBoundingClientRect();"
               " return [b.dataset.action, Math.round(r.width), Math.round(r.height)]; });") or []
    if len(boxes) != 2:
        fails.append("expected two buttons to measure, got %r" % boxes)
    for action_id, width, height in boxes:
        if width < 56 or height < 56:
            fails.append("%s: %dx%d is under the 56px target (theme %s)"
                         % (action_id, width, height, theme))

    # A <button>, not a styled div: focusable, announced, and no tap delay.
    tags = js("return Array.from(document.querySelectorAll('#shortcuts .shortcut'))"
              ".map(function (b) { return b.tagName; });") or []
    if set(tags) != {"BUTTON"}:
        fails.append("the shortcuts are not <button> elements: %r" % tags)

    # --- 3. a press carries an id and nothing else --------------------------
    js("window.__sent = []; window.__accept = true;")
    if not press("mute-mic"):
        fails.append("no mute-mic button to press")
    handed = sent()
    if handed != ["mute-mic"]:
        fails.append("a press handed the bridge %r" % handed)
    for item in handed:
        if "/" in item or ":" in item or "http" in item:
            fails.append("a press handed the bridge something url-shaped: %r" % item)

    # The result arrives later, from Java's thread, and the button has to
    # survive not hearing back immediately.
    js("window.onActionResult('mute-mic', true);")
    time.sleep(0.1)
    if not ids():
        fails.append("the buttons vanished after a press")

    # A failure has to be visible as more than a colour -- the panel is read
    # from across a desk, and `plain` has no palette to say it with.
    js("window.__sent = [];")
    press("mute-audio")
    js("window.onActionResult('mute-audio', false);")
    time.sleep(0.1)
    after = js("return document.querySelector('#shortcuts [data-action=\"mute-audio\"]')"
               ".textContent.trim();") or ""
    before = js("return (window.strings ? strings(null).actions['mute-audio'] : '');") or ""
    if before and after == before:
        fails.append("a failed press said nothing: the caption is unchanged (%r)" % after)

    # --- 4. the buttons are dead while the PC is away -----------------------
    # The rule that matters most, and the one with no visible evidence: the
    # panel is black at the time, so "nothing happened" is also what a working
    # button looks like.
    js("window.onActionResult('mute-audio', true);")
    time.sleep(1.4)
    js("window.__sent = []; window.onPcState(false);")
    press("mute-audio")
    press("mute-mic")
    offline_sent = sent()
    if offline_sent:
        fails.append("a press while the PC was away reached the bridge: %r" % offline_sent)

    # And nothing is queued: coming back must not fire what was pressed in the
    # dark.
    js("window.onPcState(true);")
    time.sleep(0.3)
    if sent():
        fails.append("presses made while offline fired on reconnect: %r" % sent())

    # --- 5. a bridge that refuses is not a bridge that is silent ------------
    js("window.__sent = []; window.__accept = false;")
    press("mute-audio")
    if sent() != ["mute-audio"]:
        fails.append("a refused press did not reach the bridge at all")
    time.sleep(1.4)
    # No result is coming for a refused press, so the button has to settle
    # itself -- otherwise it sits in its pressed state for ever.
    busy = js("return !!document.querySelector('#shortcuts [data-action=\"mute-audio\"]')"
              ".dataset.busy;")
    if busy:
        fails.append("a button left pressed for ever after the bridge refused")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", metavar="NAME",
                    help="start on this theme instead of the default")
    args = ap.parse_args()

    url = "file://" + os.path.abspath(PANEL)
    query = []
    if args.theme:
        query.append("theme=" + urllib.parse.quote(args.theme))
    if query:
        url += "?" + "&".join(query)
    print("desk-panel action check -- %s" % url)

    profile = tempfile.mkdtemp(prefix="desk-panel-actions-")
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
        # The 56px assertion is a measurement, so the window has to be the one
        # the panel is built for rather than whatever Firefox opened with.
        cl.calibrate(m, *cl.VIEWPORT)
        time.sleep(cl.SETTLE_SECONDS)
        check(m, fails, args.theme or "neon")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    for line in fails:
        print("    FAIL %s" % line)
    print("FAIL: the shortcut contract is broken" if fails
          else "PASS: the right buttons, 56px, an id and nothing else, and dead while the PC is away")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
