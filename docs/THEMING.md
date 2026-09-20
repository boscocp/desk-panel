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
the console — once, not once a minute. The server does not validate it, because
the server has no idea which themes the installed APK was built with.

In a browser, `web/index.html?theme=plain` does the same thing through
`js/mock.js`. `python e2e/layout/check_layout.py --theme plain` measures it at
the phone's real viewport.

## What you may use

- **`js/format.js`** is loaded before every theme, and its functions are
  globals: `formatPrice`, `formatRate`, `formatPair`, `formatChange`,
  `changeClass`, `formatTemp`, `weatherLabel`, `formatBattery`, `tempClass`,
  `sparklinePath`, `isNight`. Use them. A theme that reimplemented
  `formatPrice` would reintroduce the sub-1 rounding bug the yuan found in
  T6.5, once per theme.
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
  `crypto`, `weather`, `battery`, `stale-badge`, `shortcuts`. Nothing breaks if
  you do not, but `e2e/layout/measure.js` measures those eight sections — is
  anything off screen, does a card clip its own content, does one section's ink
  land on another's — and a theme that renames them opts out of the only check
  that has ever caught a layout bug here.

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

Your `tick` also stops being called while the panel is dark, so do not hang
anything on it that has to keep running. Nothing does.

## Checking it

```bash
node --test "web/test/**/*.test.js"          # format.js, which you did not change
python e2e/layout/check_layout.py --theme <name>
```

The layout check drives a real browser at 872x392 — the phone's actual
viewport — and runs two payloads: the served one from `mock.js`, and the
widest case the panel can legitimately be asked to show
(`e2e/layout/stress.js`: the longest city, the longest weather label, a
negative temperature, a six-figure price beside a sub-1 one, a ticker far
longer than five characters, and the STALE badge shown). The second one is the
one that fails.

Then look at it on the device, because the harness cannot: Android resolves
`sans-serif-condensed` to Roboto Condensed and the desktop falls back to
something wider, so measured text widths are a conservative estimate rather
than the truth.
