# Layout check

Measures `web/index.html` at the phone's real viewport and fails if any section is off screen
or clipped. No phone needed — unlike the adb suite one directory up, this runs on the host.

Built during T6.1, which existed because the fifth card had been hanging off the bottom of the
screen for two tasks while every screenshot looked fine.

## Prerequisites

- **Firefox** on `PATH`. This drives Firefox over **Marionette**, its built-in automation
  protocol — not Chrome, and not Selenium. No driver binary, no npm, no pip: Python standard
  library only, like `server/`.

## Running

```bash
python e2e/layout/check_layout.py
echo $?    # 0 = every section fits, 1 = something clips, 2 = the harness could not run
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

Three things, because "it rendered" answers none of them and a screenshot only answers the
first:

1. `documentElement.scrollHeight` against the viewport — is the page taller than the screen.
2. Every element under `body` against the viewport box — did one card escape.
3. Every section's `scrollHeight` against its `clientHeight` — is the card on screen but its
   contents not. Cards use `overflow: hidden`, so this failure is completely silent.

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

Worth doing after any change to `measure.js`.

## Why 872x392

The Redmi Note 10's landscape WebView viewport in CSS px. It is 2400x1080 physical at 440dpi,
and the width is **872 rather than 839** because `MainActivity` sets
`LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES` and claims the camera cutout strip (T2.3).
Measured on the device, not derived on paper. Do not round it off; if the cutout mode ever
changes, this number changes with it and the layout has to be measured again.

## The two passes

`served` runs the page as `mock.js` feeds it. `stress` then pushes the widest case the panel
can legitimately be asked to show — the longest weather label in `format.js`, a long city name,
a negative temperature, a six-figure and a sub-1 crypto price together, a symbol far longer
than a ticker, a zero change, the STALE badge, a 23:59:59 clock and a pt-BR date as the phone
renders it.

Both passes matter. The typical tick is not what breaks a layout, and `stress.js` says beside
each value why it is there.

## Who should use this

- **T6.2** (glow, burn-in shift) — a shift that moves pixels can move them off screen.
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
