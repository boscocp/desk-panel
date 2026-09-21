# Layout check

Measures `web/index.html` at the phone's real viewport and fails if any section is off screen,
clipped, or drawn on top of another one. No phone needed — unlike the adb suite one directory
up, this runs on the host.

Built during T6.1, which existed because the fifth card had been hanging off the bottom of the
screen for two tasks while every screenshot looked fine.

## Prerequisites

- **Firefox** on `PATH`. This drives Firefox over **Marionette**, its built-in automation
  protocol — not Chrome, and not Selenium. No driver binary, no npm, no pip: Python standard
  library only, like `server/`.

## Running

```bash
python e2e/layout/check_layout.py
echo $?    # 0 = the layout is sound, 1 = something is wrong, 2 = the harness could not run
```

Useful flags:

```bash
python e2e/layout/check_layout.py --screenshots /tmp/panel   # a PNG per pass
python e2e/layout/check_layout.py --viewport 839x392         # some other screen
python e2e/layout/check_layout.py --extra-css bigger.css     # try a size change
```

`--extra-css` injects a stylesheet before measuring, so you can answer "would 24px type still
fit?" without editing `web/` and without a rebuild.

## What it measures

Four things, because "it rendered" answers none of them and a screenshot only answers the
first:

1. `documentElement.scrollHeight` against the viewport — is the page taller than the screen.
2. Every element under `body` against the viewport box — did one card escape.
3. Every section's `scrollHeight` against its `clientHeight` — is the card on screen but its
   contents not. Cards use `overflow: hidden`, so this failure is completely silent.
4. Every section's **ink** against every other section's — is one thing drawn on top of
   another. Added in T5.4, which is the bug that earned it: the battery corner line is
   positioned absolutely and was set to `nowrap`, so its longest variant grew out of its column
   and painted an opaque black box over the bottom of the CRYPTO card, hiding a live price's
   change and its sparkline. Everything fitted. Everything was on screen. Nothing clipped.

   Ink, not boxes, and the distinction is the whole design: `#battery` shares a rectangle with
   the WEATHER card deliberately, and `#stale-badge` with `#panel`, so a box comparison would
   either fail on both of those or have to allowlist the exact pair the bug was in. So it
   compares the leaf elements that carry text and each sparkline's `<path>`. Sharing empty space
   is fine. Sharing a pixel with a glyph in it is not.

It also fails if a section renders **empty**. That is not a nicety: an empty card always fits,
and before T6.1 the panel looked acceptable on the device for exactly that reason — the cards
were empty outlines, because `mock.js` only runs under `file://` and the APK serves over
`https://appassets.androidplatform.net/`. Without this check the harness would be loudest
precisely when it was measuring nothing.

## The trap: calibrate the viewport, do not assume it

`SetWindowRect`, Firefox's `--window-size` and Chrome's equivalent all size the **outer
window**, not the layout viewport. Asking for 872x392 on the machine this was written on gave
an `innerHeight` of **306** — 86px short.

Every measurement against that is wrong **in the reassuring direction**: a page that fits a
viewport 86px shorter than the real one trivially fits the real one, so the check passes on a
layout that clips on the phone. `calibrate()` therefore asks, reads `innerWidth`/`innerHeight`
back, corrects by the difference and repeats — and refuses to measure at all if it does not
converge. Whatever you port this to, port that with it.

## Checking that it still catches anything

A check that has never failed proves nothing. To see it fail on demand, put back the clock size
T1.1 shipped and that T2.3 reported as the overflow:

```bash
echo '#clock { font-size: 160px; }' > /tmp/regress.css
python e2e/layout/check_layout.py --extra-css /tmp/regress.css
echo $?    # 1, reporting #clock content 710x192 in a box of 296x192
```

For the overlap check, take the cap off the battery line — which is how the T5.4 bug looked:

```bash
printf '#battery { max-width: none; white-space: nowrap; }\n' > /tmp/regress2.css
python e2e/layout/check_layout.py --extra-css /tmp/regress2.css
echo $?    # 1, on the stress pass: #crypto "-4.5%" overlaps #battery ... over 68x15px
```

Worth doing after any change to `measure.js`.

## Why 872x392

The Redmi Note 10's landscape WebView viewport in CSS px. It is 2400x1080 physical at 440dpi,
and the width is **872 rather than 839** because `MainActivity` sets
`LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES` and claims the camera cutout strip (T2.3).
Measured on the device, not derived on paper. Do not round it off; if the cutout mode ever
changes, this number changes with it and the layout has to be measured again.

## The three passes

`served` runs the page as `mock.js` feeds it. `stress` then pushes the widest case the panel
can legitimately be asked to show — the longest weather label in `format.js`, a long city name,
a negative temperature, a six-figure and a sub-1 crypto price together, a symbol far longer
than a ticker, a zero change, the STALE badge, a 23:59:59 clock and a pt-BR date as the phone
renders it.

All three matter. The typical tick is not what breaks a layout, and each fixture says beside
its values why they are there.

### `overflow`, which is the odd one out

`overflow.js` feeds more rows than any card on either theme can show, and it is the only pass
here that requires something to **happen**. Everything else on this page checks that nothing
went wrong — and a card that silently swallows its extra rows passes every one of those
checks. That is precisely what the panel did until T6.6, and why a sixth ticker was invisible
rather than broken.

So this pass asserts the other direction, and fails both ways round:

- a section whose content does not fit and which does **not** carry `data-scroll` is a card
  hiding a row in silence,
- a section that carries `data-scroll` with nothing hidden is motion for its own sake, on a
  panel that sits in someone's peripheral vision all day,
- and if no section is scrolling at all, the pass fails rather than passing quietly — either
  the feature regressed or the fixture stopped overflowing the cards it was written for.

`data-scroll` is part of the theme contract, not neon's private detail: see
`docs/THEMING.md`. What this pass cannot see is whether the card keeps moving across a refresh
— it measures one frame, and `window.onData` replaces every row in every card once a minute.
`check_scroll.py` beside it is the one that drives that over time.

 `measure.js` also intersects a rect with the boxes that clip it before
judging it, so a row waiting its turn below the fold is not reported as a card escaping the
screen — scoped to `[data-scroll]` deliberately, because clipping every rect against every
`overflow: hidden` ancestor would quietly gut the "outside the viewport" question.

## Every pass is measured seven times, once per burn-in position

T6.2 made the panel move. It shifts a few pixels every four minutes so that one unchanging
layout does not etch itself into an AMOLED, which means "where is this card" now has seven
answers and a harness that took one of them would be checking the worst case one run in
seven. A card that only escapes the viewport at `(-4,-3)` would have been a check that failed
on a Tuesday.

So each pass runs `measure.js` once per position in the cycle, and the report lists them:

```
burn-in  measured at 7 of the cycle's positions: (-4,0) (0,0) (-3,-1) (-1,-4) ...
```

Two things are asserted that a single measurement cannot be:

- **the offset reaches the glass.** The shift is two custom properties on `<html>` and one
  rule in `web/css/style.css`; if either goes, the sweep still runs, still measures seven
  times, and would still report a pass — having measured one position seven times. Every
  position is therefore checked against where the panel actually went.
- **the panel moves at all.** If every position in the cycle is the same offset, nothing is
  protecting the display, and that is a failure rather than a very stable panel.

Findings already reported at the first position are not repeated for the other six: a card
that does not fit anywhere is said once.

### The clock is pinned first, and that fixed two things

The sweep sets the panel's clock to a chosen minute, and a payload arriving a moment later
repaints the clock from `new Date()` — which put the panel straight back where the wall clock
said it should be. So the harness replaces the page's `Date` with one pinned to a fixed
instant before it measures anything.

Two consequences beyond the sweep working at all:

- the `stress` pass's pt-BR date used to be **today's**, so "the widest case the panel can be
  asked to show" was only the widest case on the days it happened to be. It is pinned to
  Monday 23 February 2026 — `segunda-feira, 23 de fevereiro de 2026`, the longest such date
  of the year at 38 characters.
- the screenshots are comparable between runs again, which is what `--screenshots` is for.

One trap, and it cost a debugging session: **`new Date()` inside an injected script is not the
page's `Date`.** Marionette executes in its own sandbox with its own globals, so a bare
`new Date()` there reads the wall clock however carefully the page's one has been pinned.
`check_layout.py` and `stress.js` both say `new window.Date()`. It is the same cross-realm
trap that made `instanceof Date` the wrong guard inside `offsetFor` — that one answered the
origin for every clock the sweep handed it, and seven positions measured as one.

## The other four checks in this directory

`check_layout.py` measures one frame. Four siblings answer what a frame cannot, all of them
driving the same Marionette plumbing so this is five checks and one harness:

| | asks |
|---|---|
| `check_blackout.py` | does the panel go dark on both causes, hold what arrives, and draw it on the way back (T6.7) |
| `check_scroll.py` | does an overflowing card keep moving across a refresh (T6.6) |
| `check_pulse.py` | does a value pulse **only** when it changed (T6.2) |
| `check_night.py` | does the panel run its night profile inside the configured window (T6.4) |

`check_night.py` is the only one that deliberately does **not** pin or freeze the page's
clock: what it is testing is that the page compares the payload's window against *now*, so a
pinned clock would let a page ignoring the bounds pass whenever it happened to agree. It also
carries a lesson worth repeating in the next check somebody writes here — its fixtures name
the theme under test, because `host.useTheme` falls back to `neon` on an absent name, and the
first cut reported `--theme plain` as passing while measuring neon.

`check_pulse.py` is the one that is about a theme rather than about the panel: `neon` lifts a
changed value toward a brighter accent for 280ms, `plain` deliberately does nothing. Run it
for the themes that pulse. What it is really guarding is invisible here and obvious on the
desk — `window.onData` replaces every row every minute whether or not a number moved, so a
theme that pulsed on "a payload arrived" would look perfect in a browser whose fixture
jitters every price, and would flash the whole panel once a minute with the upstream down and
STALE in the corner saying nothing had moved.

## Who should use this

- **T6.7** (a theme boundary) moved markup around, which is exactly what the overlap check is
  for; **T6.6** (slow scroll on overflow) is where the `overflow` pass came from.
- **T6.2** (glow, burn-in shift) — a shift that moves pixels can move them off screen, which
  is why every pass is now measured at every position in the cycle. `check_pulse.py` came from
  the same task.
- **T6.3** (device legibility) — it raises type sizes, and its acceptance forbids any font
  under 20px. `--extra-css` will tell you whether a size still fits before you commit to it.
- **T6.4** (night profile) — if the night profile changes any metric, re-measure.
- **TT.7** (Espresso-Web) — the on-device equivalent. This harness cannot see the real font:
  Android resolves `sans-serif-condensed` to Roboto Condensed and the host falls back to
  something wider, so text widths here are a conservative estimate, never the truth.

## What it cannot tell you

Whether the panel is *readable*. Nothing here measures contrast, glow or type size against a
human at 50cm — that is T6.3, on the device, with eyes. A green check means "it fits", never
"it looks right".
