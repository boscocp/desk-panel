"""Assert the night profile in a real browser. Exits non-zero on any failure.

    python e2e/layout/check_night.py [--theme NAME]

T6.4: inside a window the PC's config describes, the panel dims. The half of
that a browser can see is the page's -- `js/app.js` puts `data-night` on
`<html>`, `css/style.css` stops every animation under it, and the live theme
drops its glow. The other half is the backlight, which is
`WindowManager.LayoutParams.screenBrightness` on a real phone and is covered
by the `night=` marker instead.

Four questions, and each one is a way of getting this wrong that looks
perfectly fine on this desk in the afternoon:

  1. **the window is read against the device's clock, minute by minute.** The
     payload carries two strings and never a boolean, precisely so that the
     panel decides. A page that had let the server decide would pass every
     test that only ever ran in one timezone.
  2. **the panel keeps moving at night, and that is the assertion.** It used
     to be the opposite: core removed every animation under the attribute, on
     the argument that a card walking through its hidden rows at 03:00 is the
     only thing here that can wake somebody. T6.14 removed that rule from the
     chair, because the panel is lit only while the PC is on and logged in
     (invariant 3) -- the dark room it was protecting has somebody awake at a
     machine in it. The check was inverted rather than deleted: a card that
     stops at night is now a regression, and an assertion nobody inverts is
     the one that hides a change.
  3. **the glow drops.** A theme's half, and the only question here that is
     about taste; `neon` halves three custom properties and `plain` has
     nothing to dim.
  4. **none of it applies to a panel nobody can see.** Offline the screen is
     asleep; and letting the two states overlap would mean a card blacked out
     at night lost its scroll position, because `none` restarts what `paused`
     resumes.

The window is computed from the harness's own clock rather than pinned, which
is the opposite of what `check_layout.py` does and is right for the opposite
reason: that file measures a layout and needs the same instant every run, and
this one is testing that the page compares a window against *now*. A pinned
clock here would let a page that ignored the payload's bounds pass, as long as
it happened to agree.

Driven through check_layout.py's Marionette plumbing -- same Firefox, same
launcher -- so a fifth browser check is not a fifth browser harness.
"""

import argparse
import datetime
import json
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

# The one theme that glows. Question 3 is required of it and reported as
# absent for anything else -- the same shape check_pulse.py takes, and for the
# same reason: a theme owes the panel no glow at all (docs/THEMING.md), so a
# missing one is not a failure, but neon losing its glow silently would be.
GLOWING_THEME = "neon"

# Enough B3 rows to overflow the tallest card on either theme, so that there
# is actually an animation running when question 2 takes it away. Twelve, for
# the reason e2e/layout/overflow.js gives.
ROWS = 12


def hhmm(minute_of_day):
    """A payload bound, from minutes since local midnight."""
    minute_of_day %= 24 * 60
    return "%02d:%02d" % (minute_of_day // 60, minute_of_day % 60)


def payload(theme, night_start, night_end):
    """The overflowing fixture, carrying one night window.

    `theme` rides every fixture, and leaving it out is not the harmless
    omission it looks like: `host.useTheme` falls back to neon on an absent
    name, so the first payload of a `--theme plain` run would switch the page
    back to the default and every assertion after it would be about neon
    again. The first cut of this file did exactly that, and reported plain as
    passing while measuring neon's glow.
    """
    body = {
        "theme": theme,
        "quotes": [{"symbol": "Q%d" % i, "price": 10 + i, "changePct": i % 3 - 1}
                   for i in range(ROWS)],
        "fx": [],
        "crypto": [],
        "weather": {"tempC": 21, "minC": 18, "maxC": 24, "code": 0, "city": "A"},
        "battery": {"level": 50, "tempC": 30, "charging": False},
        "stale": False,
        "night": {"start": night_start, "end": night_end},
    }
    return "window.onData(%s);" % json.dumps(body)


def windows(now):
    """A window that certainly contains `now`, and one that certainly does not.

    Two hours wide and three hours away respectively, so neither can be
    decided by which side of a minute boundary the page and this file happen
    to land on. Both are built with modular arithmetic and so both wrap
    midnight when the clock does -- which is not a special case being avoided
    but the default window's own shape (22:00 to 07:00), exercised for free
    once a night.
    """
    minute = now.hour * 60 + now.minute
    return ((hhmm(minute - 60), hhmm(minute + 60)),
            (hhmm(minute + 180), hhmm(minute + 240)))


def check(m, theme, fails):
    def js(src):
        return m.script(src)

    def night_attr():
        return js("return document.documentElement.getAttribute('data-night');")

    def glow():
        return js("return getComputedStyle(document.documentElement)"
                  ".getPropertyValue('--glow').trim();")

    # The outermost element inside #quotes whose computed animation-name is
    # not 'none', found by what it does rather than by what it is called: a
    # theme is free to answer an overflow however it likes and to name its
    # moving box whatever it likes. `[0]` is the card's scroller -- an
    # ancestor precedes its descendants in document order, and a pulsing
    # value is a second animation further in (T6.2).
    MOVING = ("(Array.from(document.querySelectorAll('#quotes *'))"
              ".map((el) => getComputedStyle(el))"
              ".filter((s) => s.animationName !== 'none')[0] || {})")

    def animating():
        """The computed animation-name of whatever is moving inside #quotes.

        Found by what it does rather than by what it is called: a theme is
        free to answer an overflow however it likes and to name its moving box
        whatever it likes. `[0]` is the outermost such element, which is the
        one carrying the card's scroll -- an ancestor precedes its descendants
        in document order, and a pulsing value is a second animation further
        in (T6.2).
        """
        return js("return %s.animationName || 'none';" % MOVING)

    def shadows():
        """Every rendered glow on the panel, as the strings the browser computes.

        Read off what is on screen rather than off the custom properties, so a
        theme that stopped spending `--glow` would be caught as surely as one
        that stopped defining it.
        """
        return js("return Array.from(document.querySelectorAll('body *'))"
                  ".map((el) => { const s = getComputedStyle(el);"
                  "  return s.textShadow + '|' + s.boxShadow; })"
                  ".filter((v) => v.indexOf('none|none') !== 0);")

    # mock.js pushes its own payload every three seconds on a file: page, with
    # the shipped 22:00-07:00 window in it, which would overwrite every fixture
    # below within one assertion. Clearing every interval id is blunt and is
    # the only handle available -- mock.js keeps its id to itself, deliberately
    # (nothing in production has any business stopping the feed). It stops
    # app.js's clock too, which costs nothing here: the night profile is
    # re-evaluated on a payload and on a screen transition, never on a tick.
    js("for (let i = 1; i < 10000; i += 1) { clearInterval(i); }")

    inside, outside = windows(datetime.datetime.now())

    # --- day, and it is the baseline every night assertion is read against --
    js(payload(theme, *outside))
    # Asserted rather than assumed, because the failure it guards against is
    # silent: a run measuring the wrong theme passes, and says so.
    live = js("return (document.querySelector('link[rel=\"stylesheet\"]"
              "[data-theme][media=\"all\"]') || {}).dataset.theme;")
    if live != theme:
        fails.append("asked for the %r theme and the page is running %r"
                     % (theme, live))
    if night_attr() is not None:
        fails.append("a window that does not contain now put the panel in its "
                     "night profile: %s-%s" % outside)
    day_glow = glow()
    day_shadows = shadows()

    # Answering an overflow with motion is optional in the theme contract
    # (docs/THEMING.md) -- `check_scroll.py` guards on the same attribute for
    # the same reason -- so question 2 is asked of a theme that actually
    # moves and reported as not applicable for one that does not. Both are
    # needed: without the attribute a theme that stopped scrolling would pass
    # question 2 by having nothing to stop, and without the skip a conformant
    # theme would fail a check docs/TESTING.md requires of every theme.
    scrolls = js("return !!document.querySelector('#quotes[data-scroll]');")
    day_animation = animating() if scrolls else "none"
    if scrolls and day_animation == "none":
        fails.append("a card holding %d rows declares data-scroll and is not animating "
                     "in the day profile, so question 2 would have been checked "
                     "against nothing" % ROWS)

    # --- night ------------------------------------------------------------
    js(payload(theme, *inside))
    if night_attr() != "on":
        fails.append("a window containing now did not put the panel in its night "
                     "profile: %s-%s" % inside)

    # Inverted by T6.14, and the inversion is the assertion. Core used to
    # remove every animation under data-night; it does not any more, because
    # the panel is lit only while somebody is logged in at it (invariant 3) and
    # the owner asked for the loop to keep running. The check has to say so out
    # loud rather than simply stop asking: a card that stopped moving at night
    # would now be a regression, and the shape of this file's history is that
    # the assertion nobody inverted is the one that hid the change.
    if not scrolls:
        print("    note: %s answers an overflow without motion, so question 2 is not "
              "asked of it" % theme)
    elif animating() == "none":
        fails.append("a card stopped animating at night, which T6.14 removed: the "
                     "night profile dims the panel and no longer freezes it")

    night_shadows = shadows()
    if theme == GLOWING_THEME:
        if not day_shadows:
            fails.append("%s rendered no glow at all in the day profile, so the "
                         "drop below could not be measured" % theme)
        elif night_shadows == day_shadows:
            fails.append("%s renders exactly the same glow at night as by day"
                         % theme)
        if not day_glow:
            fails.append("%s does not define --glow, which is what its night block "
                         "redefines" % theme)
        elif glow() == day_glow:
            fails.append("%s: --glow is unchanged at night: %r" % (theme, day_glow))
    elif night_shadows != day_shadows:
        # Not a failure -- a theme may dim whatever it likes -- but worth a line,
        # because a theme growing a night profile is the moment to add it here.
        print("    note: %s changes its shadows at night; only %s is asserted on"
              % (theme, GLOWING_THEME))
    else:
        print("    note: %s has no glow to dim, so question 3 is not asked of it"
              % theme)

    # --- and none of it applies to a panel nobody can see -------------------
    #
    # Both causes, because they are two different paths into applyScreen and
    # the profile has to come off for either. The payload stays the same one:
    # what changes is whether the panel is visible.
    for name, go_dark, come_back in (
            ("offline", "window.onPcState(false);", "window.onPcState(true);"),
            ("thermal", "window.onThermal(true);", "window.onThermal(false);")):
        js(go_dark)
        if night_attr() is not None:
            fails.append("%s: the night profile stayed on a panel nobody can see"
                         % name)
        js(come_back)
        if night_attr() != "on":
            fails.append("%s: the night profile did not come back with the panel"
                         % name)

    # The scroll survives a blackout *at* night, which is the whole reason the
    # two states are kept apart rather than stacked: `paused` resumes where it
    # left off and `none` starts again, so a card dark at 03:00 must be paused
    # and not removed.
    if scrolls:
        js("window.onThermal(true);")
        dark_state = js("return %s.animationPlayState || 'missing';" % MOVING)
        if dark_state != "paused":
            fails.append("a card blacked out at night is not merely paused: %r"
                         % dark_state)
        js("window.onThermal(false);")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", metavar="NAME", default=GLOWING_THEME,
                    help="start on this theme instead of the default")
    args = ap.parse_args()

    url = "file://" + os.path.abspath(PANEL)
    if args.theme:
        url += "?theme=" + urllib.parse.quote(args.theme)
    print("desk-panel night check -- %s" % url)

    profile = tempfile.mkdtemp(prefix="desk-panel-night-")
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
        # The last checks need a card that is genuinely overflowing, and how
        # many rows overflow a card depends on how tall the card is. In
        # whatever window Firefox opened with, twelve may well fit.
        cl.calibrate(m, *cl.VIEWPORT)
        time.sleep(cl.SETTLE_SECONDS)
        check(m, args.theme, fails)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    for line in fails:
        print("    FAIL %s" % line)
    print("FAIL: the night profile is broken" if fails
          else "PASS: the panel dims inside its window, keeps moving, and only "
               "while somebody can see it")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
