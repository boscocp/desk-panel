# Writing a theme

A theme decides everything the panel looks like: which elements exist, what
order they are in, what shape a card is, and every colour. It cannot decide
where the numbers come from, when the screen is lit, or what the payload
means — those belong to the core, and three of them are project invariants.

If you only want different colours, you still write a theme; there is no
shallower hook, deliberately. Copy `web/themes/neon/theme.css`, change the
custom properties at the top, and reuse `neon`'s `theme.js` verbatim.

## The shape of a theme

```
web/themes/<name>/
    theme.js     registers the theme and builds the markup
    theme.css    its stylesheet, and the only one that will be live
```

`theme.js` ends with one line:

```js
window.DeskPanel.defineTheme('<name>', { render, tick });
```

Two functions, and that is the whole interface:

```js
function render(payload, root)   // the data changed: rebuild what shows it
function tick(now, root)         // one second passed: `now` is a Date
```

`root` is `document.body`, and everything inside it is yours. Nothing in core
puts an element there.

`render` is called when a payload arrives (about once a minute on the device),
when the theme is first selected, and once at page load with `payload` set to
**`null`** — there is no data yet and the clock is still worth showing. Handle
that case; `neon` builds its skeleton and leaves the cards empty.

`tick` is called once a second while the panel is lit, and once immediately
after every `render`. Keep it cheap: it is the only thing that runs on a panel
nobody is touching.

Neither is called while the panel is dark — see the blackout below.

Neither function may assume it was called before. Core empties `root` when the
theme changes, so build your skeleton if it is not there:

```js
function ensure(root) {
    if (!els || els.root !== root || !root.contains(els.clock)) {
        mount(root);
    }
}
```

A flag would be wrong here — it would claim "mounted" about a DOM that was
emptied underneath it.

## Registering it

`web/index.html` carries the packaged-theme manifest: two lines per theme, the
stylesheet and the script.

```html
<link rel="stylesheet" href="themes/plain/theme.css" data-theme="plain" media="not all">
...
<script defer src="themes/plain/theme.js"></script>
```

`media="not all"` on every theme but the default: `js/host.js` flips it to
`all` on the one that wins, so switching is a property change on a stylesheet
the browser already has rather than a request.

Both lines are load-bearing. The script must be in the deferred list rather than
injected, because `#clock` has to exist before the page finishes loading — the
Android side reads it out of the DOM to log `panel=rendered` (ADR 0009), and an
injected script runs too late for that.

Adding a theme therefore means adding a directory and two lines, and it needs a
rebuild — the files have to get into `assets/` somehow. **Switching between
packaged themes does not**, which is the rule that matters.

## Selecting one

The `theme` key in `server/config.toml` on the PC. It rides the `/quotes`
response into the payload, and the page picks the matching directory out of the
set the APK carries. Edit the file, restart the server, and the panel changes at
its next poll.

A name no packaged theme answers to falls back to `neon` and writes one line to
the console — once per name, not once a minute, so a second typo months later is
still reported. The server does not validate it, because the server has no idea
which themes the installed APK was built with.

In a browser, `web/index.html?theme=plain` does the same thing through
`js/mock.js`. `python e2e/layout/check_layout.py --theme plain` measures it at
the phone's real viewport.

## What you may use

- **`js/format.js`** is loaded before every theme, and its functions are
  globals: `formatPrice`, `formatRate`, `formatPair`, `formatChange`,
  `changeClass`, `formatTemp`, `formatRange`, `weatherLabel`, `weatherGlyph`,
  `formatBattery`, `tempClass`, `sparklinePath`, `isNight`, `overflowsBy`,
  `scrollPlan`, `worthScrolling`. Use them. A theme that reimplemented `formatPrice` would
  reintroduce the sub-1 rounding bug the yuan found in T6.5, once per theme —
  and one that joined a daily low and high with a hyphen would reintroduce
  `-12-42`, which is what `formatRange` exists to stop (T6.8).
- Anything in your own directory.

## What you may not do

- **No network.** Not `fetch`, not `XMLHttpRequest`, not an `<img src>` off the
  device, not a webfont. The WebView is served from
  `https://appassets.androidplatform.net/` with mixed content blocked, and all
  I/O is native Java (invariant 1, ADR 0002). A remote font does not fail
  loudly; it simply never arrives.
- **No `visibility: visible`.** See the blackout below.
- **Do not rename `clock`.** One id is core's: an element with `id="clock"`
  holding exactly `HH:MM:SS`. `MainActivity` reads it on every page load and
  logs `panel=rendered clock=…`, which is the app's only evidence that the
  asset pipeline, the https origin, JavaScript and the DOM all worked (T2.2,
  ADR 0009). The E2E suite greps for it.
- **Prefer the conventional ids for the rest.** `date`, `quotes`, `fx`,
  `crypto`, `weather`, `battery`, `stale-badge`. Nothing breaks if you do not,
  but `e2e/layout/measure.js` measures exactly those seven plus `clock` — is
  anything off screen, does a card clip its own content, does one section's ink
  land on another's — and a theme that renames them opts out of the only check
  that has ever caught a layout bug here.

  `shortcuts` is **not** in that list, and both themes still use the name: it is
  the reserved strip in the sidebar that T8.2's buttons will fill, and it holds
  nothing to measure until they do.

## A card that hides a row has to say so

The panel is exactly one screen. Every card clips, which is what stops a sixth
ticker arriving from server config pushing a section off the bottom edge — and
until T6.6 that was the whole story, so the sixth ticker was not truncated and
not marked, it was simply absent with nothing on the panel saying so.

A theme may answer that however it likes. Both of the ones in the repo walk the
rows slowly past a window; a theme could shrink them, paginate them, or put a
count in the corner instead. What is **not** optional is the accounting:

- If a section is showing less than it was given, put **`data-scroll`** on that
  section for as long as that is true, and take it off when it stops being.
- If a section carries `data-scroll`, something inside it must actually be
  hidden. Motion with nothing to reveal is worse than none: this panel sits in
  someone's peripheral vision all day.

`e2e/layout/measure.js` reads the attribute, and `check_layout.py` fails a pass
in both directions — a card overflowing without it, and a card claiming it with
everything on screen. That pair is the only machine-checkable statement of "no
row is hidden in silence", and it is why the harness has a third fixture
(`e2e/layout/overflow.js`, more rows than any card can show) alongside the
served and stress ones.

The arithmetic is not yours to invent either. `overflowsBy(rowCount,
visibleRows)` says how many rows are hidden, `scrollPlan(rowCount, visibleRows,
secondsPerRow, movingFraction)` returns `null` or `{hidden, seconds}`, and
`worthScrolling(travelPx)` says whether the pixels those rows came out to are
worth moving for at all; you measure, they decide.

That last one is not optional politeness. `clientHeight` and `scrollHeight` are
integers and the device lays out at a device pixel ratio of 2.75, so a card
whose rows exactly fill it can measure a pixel over — one hidden row, one pixel
of travel, and a card twitching in the corner of someone's eye for as long as
the panel is on, with every check in `e2e/layout` passing because a pixel of
overflow is a real overflow as far as a measurement can tell. Both are pure and tested, and the two
numbers you pass in are your own — read them off a custom property so they stay
in your stylesheet next to the `@keyframes` block they describe, the way both
themes do.

**Whatever moves must not be rebuilt.** `window.onData` replaces every row in
every card once a minute. Put the animation on an element your `mount()` builds
once and your `render()` only refills: a CSS animation belongs to an element,
and replacing that element's children does not disturb it. Rebuild the animated
element itself and the card resets to the top every 60 seconds and never
reaches the rows it is moving to reveal.

## The blackout is not yours

The panel is lit only while the PC is on and logged in (invariant 3, ADR 0005)
and the device is below its thermal ceiling (T5.5, ADR 0012). When either stops
being true, `js/app.js` puts `data-panel="dark"` on `<html>` and
`web/css/style.css` hides `body`:

```css
:root[data-panel="dark"] body { visibility: hidden; }
```

It is core rather than a per-theme rule because it is the page's half of a
promise about hardware. A theme that forgot it, or spelled its class name
differently, would leave a lit panel against a sleeping PC and look like a bug
in Java.

The one thing you owe it: **never set `visibility: visible`**, on anything. That
un-hides a descendant of a hidden parent, and it is the only way a stylesheet
can defeat the rule.

`css/style.css` also pauses every animation inside a dark panel, and that is
core for the same reason. A hidden element's animation keeps running and keeps
being recomposited; offline the device is on battery with the screen asleep, and
under the thermal cutoff it is being blanked precisely for working too hard. So
anything you animate stops on its own while the panel is dark and resumes where
it left off — you owe that rule only the courtesy of not overriding
`animation-play-state` on something inside a dark panel.

## The burn-in shift is not yours either

The panel moves. Every four minutes `js/host.js` writes a new offset into two custom
properties on `<html>`, and `css/style.css` translates every direct child of `body` by it:

```css
body > * { transform: translate(var(--burn-in-x, 0px), var(--burn-in-y, 0px)); }
```

This device is an AMOLED showing one unchanging layout for every hour the PC is on, and an OLED
pixel ages by how long it has been lit (ADR 0008). The ground is `#000000` and those pixels are
physically off, so what is at risk is the ink — the clock's glyph edges, your card borders,
your titles — and the cheap way to protect it is to keep moving it.

It is core rather than yours for the same reason the blackout is: a theme that forgot it would
look perfectly fine and quietly etch the display. You owe it three things, and they are all
things not to do:

- **Do not translate `body` or a direct child of it yourself.** `transform` does not compose by
  accumulating — the last declaration wins — so a theme that sets one on `body > *` replaces
  the shift with nothing. Animate something further in, as both themes' scrollers do.
- **Leave your padding room.** The offsets reach 4px up and left, and both themes have 10–12px
  of body padding for it to move into. A theme flush to the viewport edge would lose 4px of its
  own margin at some positions.
- **Do not expect it in a measurement.** Everything moves together, so nothing inside a card
  changes position relative to anything else, and `getBoundingClientRect` is 0–4px different
  from one minute to the next.

One consequence that is not a rule but will surprise somebody: a `transform` makes an element
the containing block for its absolutely positioned descendants. Every direct child of `body` is
therefore one, whether or not you gave it `position: relative`. Neither theme notices — `neon`
positions `#battery` and `#stale-badge` against `#panel`, which was already `relative` — but a
theme that positioned something against the page itself would find it positioned against that
child instead.

The amplitude and the cycle are `offsetFor` in `js/format.js`, which is a pure function of the
clock and tested as one. It is not in the list of formatters above because there is nothing for
a theme to call: core applies it to whatever you put in the body.

`check_layout.py` measures every pass at every position in the cycle, so a card that only
escapes the viewport at one of them is a certain failure rather than a check that fails on a
Tuesday.

## Saying which value just changed, if you want to

Optional, and `neon` does it: a value whose rendered text is not what it was a minute ago lifts
toward a brighter accent for 280ms and comes back. `plain` does nothing, which is a legitimate
answer — it has no accent to lift toward.

If you do it, the rule is the one thing worth stating, because it is easy to get backwards and
invisible when you do. **Key it on the value, never on the refresh.** `window.onData` replaces
every row in every card about once a minute whether or not a single number moved, so a theme
that flashed on arrival would look perfect in a browser — where `mock.js` jitters every price
every three seconds — and would flash the entire panel once a minute on the desk with the
upstream down, while `STALE` sat in the corner saying nothing had moved.

`neon` compares against the text the row is showing, read out of the markup a moment before it
is replaced, rather than keeping a table of its own: a symbol dropped from the PC's config
leaves nothing behind, and a theme switch — which empties the root — starts with no history
instead of pulsing the whole panel at once.

`check_pulse.py` asserts all three of those (nothing on a fresh mount, only the changed value
on a refresh, nothing at all on an identical payload) and that the pass is over inside ~300ms.
Run it for a theme that pulses; a theme that does not will fail its second question, which is
the only way that file can still fail when the feature is deleted.

**Neither of your functions is called while the panel is dark.** `tick` stops,
and a payload that arrives meanwhile is held rather than rendered — the data
poller keeps running under the thermal cutoff, because the Activity stays in the
foreground so it can notice the device cooling, and rebuilding a hidden panel
once a minute is work done by a device that is being blanked precisely for
working too hard. The held payload is always the latest one, and `render` is
called with it the moment the panel comes back, immediately followed by `tick`.

So do not hang anything on `tick` that has to keep running, and do not treat a
`render` call as "this is new since the last one" — you may have missed several.
Nothing in either theme needs to.

## Checking it

```bash
node --test "web/test/**/*.test.js"          # format.js, which you did not change
python e2e/layout/check_layout.py --theme <name>
python e2e/layout/check_blackout.py --theme <name>
python e2e/layout/check_scroll.py --theme <name>
python e2e/layout/check_pulse.py --theme <name>    # only if your theme pulses
```

The layout check drives a real browser at 872x392 — the phone's actual
viewport — and runs three payloads: the served one from `mock.js`; the widest
case the panel can legitimately be asked to show (`e2e/layout/stress.js`: the
longest city, the longest weather label, a negative temperature, a six-figure
price beside a sub-1 one, a ticker far longer than five characters, and the
STALE badge shown); and more rows than any card can fit
(`e2e/layout/overflow.js`). The second is the one that fails on sizes. The
third is the only pass that requires something to *happen* rather than
requiring that nothing goes wrong — see the section above on saying so when a
row is hidden.

`check_scroll.py` is the one that takes time rather than a measurement: it delivers more rows
than a card can show, watches the card move, delivers the identical rows again, and fails if
the movement went back to the top. That is the rule above about not rebuilding whatever moves,
and there is no other way to check it — a pure function cannot see an animation and a layout
measurement is a single frame. It also fails a card that declares a scroll and does not move,
and one that keeps a transform after the rows start fitting again. If your theme answers
overflow with something other than motion, it will fail the first of those; say so in your
theme's own notes and skip it.

`check_blackout.py` is the other half, and it is the one your theme can fail without looking
wrong: it drives the page dark on both causes and asserts that nothing is drawn while it is,
that the payload you missed arrives on the way back, and that `#clock` holds a time before any
payload at all. If you put `visibility: visible` on something, this is what tells you.

Then look at it on the device, because the harness cannot: Android resolves
`sans-serif-condensed` to Roboto Condensed and the desktop falls back to
something wider, so measured text widths are a conservative estimate rather
than the truth.
