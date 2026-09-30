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
function render(payload, root, context)   // the data changed: rebuild what shows it
function tick(now, root)                  // one second passed: `now` is a Date
```

`root` is `document.body`, and everything inside it is yours. Nothing in core
puts an element there.

`render` is called when a payload arrives (about once a minute on the device),
when the theme is first selected, and once at page load with `payload` set to
**`null`** — there is no data yet and the clock is still worth showing. Handle
that case; `neon` builds its skeleton and leaves the cards empty.

`context` is what you cannot work out for yourself, and today it carries one
key: **`context.resumed`** is true when this is the first render after the panel
has been dark. Ignore it and nothing breaks — `plain` does — but see the pulse
section below, which is the one place it matters and the place it was added for.

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
  `scrollPlan`, `worthScrolling`, `shortcutsFor`, `agendaFields` (and the two it
  is built on, `nextEvent` and `untilText`), `agendaRows`, `agendaSegments` and
  `marketClosed`. Use them. A theme that reimplemented `formatPrice` would
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

  `agenda` is in the harness's list too and is the one id that is **optional**:
  `neon` draws T9.1's next meeting in a card under its forecast, `plain` draws
  it as a line in its footer, and a theme without either is not failed for the
  absence (T6.12). Every other id there is one both themes carry, so a missing
  one is a regression and is reported as such. See *The next meeting* below.

  `shortcuts` is **not** in that list, and both themes use the name: it is the
  strip the shortcut buttons live in. It is out of the harness because it holds
  nothing when the PC has no actions enabled, which is the default — a section
  that renders empty is a harness failure, and this one is empty legitimately.
- **A card you are holding empty on purpose says `data-reserved`.** The harness
  fails a section that renders with no text — an empty card always fits, and
  before T6.1 the panel looked acceptable on the device for exactly that reason.
  A box reserved for a feature that does not exist yet is the one honest
  exception, and it declares itself rather than being allowlisted by id.

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
secondsPerRow)` returns `null` or `{hidden, seconds}`, and
`worthScrolling(hiddenPx, rowHeightPx)` says whether what those rows came out to in pixels is
worth putting a card in permanent motion for; you measure, they decide.

That last one is not optional politeness. `clientHeight` and `scrollHeight` are
integers and the device lays out at a device pixel ratio of 2.75, so a card
whose rows exactly fill it can measure a pixel over — one hidden row, one pixel
of travel, and a card twitching in the corner of someone's eye for as long as
the panel is on, with every check in `e2e/layout` passing because a pixel of
overflow is a real overflow as far as a measurement can tell. **Pass it your row height as well
as your overflow**: since T6.9 both shipped themes answer an overflow with a loop, so any
overflow at all puts the card in motion for as long as the panel is on — and a flat pixel floor
that was generous when five pixels bought five pixels of travel is not generous when five pixels
buy a permanent pass over the whole list. The floor is half a row. Both are pure and tested, and
the number you pass in is your own — read it off a custom property so it stays in your stylesheet
next to the `@keyframes` block it describes, the way both themes do.

### If you answer the overflow with a loop

Both shipped themes do, since T6.9, and the shape is worth copying because one part of it is
easy to get subtly wrong:

- **Draw the list twice** and move the box by exactly one copy. At the end of a pass the second
  copy is sitting where the first started, the animation restarts, and nothing on screen moved.
- **Measure the pitch; do not compute it.** The distance you want is the offset between a row
  and its clone — `children[n].offsetTop - children[0].offsetTop` — not the scroll height of one
  copy. If your rows carry a border or a margin between them and none after the last, a copy
  inside a pair is taller than a copy on its own, and the difference is a jolt every pass.
- **`linear`, and no `alternate`.** A loop has no ends to ease into, and the frame after the
  restart has to be indistinguishable from the frame before it, which is only true at constant
  speed.
- **Clone after you measure the overflow**, not before, or the second copy is what makes the
  card look like it overflows.

`check_scroll.py` asks all of this: an even number of rows, a second copy that says the same
thing as the first, and a travel distance equal to the measured pitch. That last one is exact —
a tolerance there would be a tolerance on the jolt.

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

The panel moves. Every minute `js/host.js` writes a new offset into two custom
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
positions `#stale-badge` against `#panel`, which was already `relative` — but a theme that
positioned something against the page itself would find it positioned against that child
instead. (`#battery` was the other one until T6.12 moved it into the flow of the sidebar.)

The amplitude and the cycle are `offsetFor` in `js/format.js`, which is a pure function of the
clock and tested as one. It is not in the list of formatters above because there is nothing for
a theme to call: core applies it to whatever you put in the body.

`check_layout.py` measures every pass at every position in the cycle, so a card that only
escapes the viewport at one of them is a certain failure rather than a check that fails on a
Tuesday.

## The words are not yours to choose

Everything a person reads off the panel comes from a language table in `js/format.js`, and the
language comes from the PC's config the same way the theme does (T6.11). `pt-BR` and `en` ship;
`pt-BR` is what an unknown tag falls back to.

```js
const words = strings(payload && payload.language);
words.titles.crypto   // 'CRIPTO'
words.stale           // 'DEFASADO'
words.weather[99]     // 'Trovoada com granizo forte'
words.unplugged       // 'na bateria'
words.tag             // 'pt-BR', for toLocaleDateString and anything else Intl
```

Read it once at the top of `render()` and keep it for that render. Both shipped themes do; both
also re-apply their headings there rather than only in `mount()`, because the language can
change under a running panel exactly as the theme can.

- **Do not write a user-facing string in your theme.** Not in the JavaScript, and not in the
  stylesheet either — `neon`'s card titles are `content: attr(data-title)` and the theme writes
  the attribute. A literal is a word that only exists in one language, and nothing will tell
  you.
- **Do not read the device's locale.** `toLocaleDateString(undefined, …)` asks the WebView,
  which on a phone in a stand says nothing about who is looking at the panel. `words.tag` is
  the answer.
- **Leave room for the other language.** The words are not the same length: `TEMPO` against
  `WEATHER`, `DEFASADO` against `STALE`. If two of them share a strip — the stale badge and a
  card title do, in `neon` — `check_layout.py --lang` is what tells you whether they still fit,
  and it can see a `::before`'s ink since T6.11.

Adding a language is a table in `format.js` and nothing else. A test asserts every table has
every key the fallback has, so a half-translated one fails before it reaches a panel.

## The night profile is half yours

Inside the window `server/config.toml` describes — `night_start` and `night_end`, 24-hour
`"HH:MM"`, evaluated against **the phone's** clock — `js/app.js` puts `data-night="on"` on
`<html>`. The window wraps midnight by default (22:00 to 07:00), and the predicate behind it
is `isNight` in `js/format.js`.

Core used to own a half of it and no longer does. There was a rule:

```css
:root[data-night] body * { animation: none !important; }   /* removed in T6.14 */
```

on the argument that peripheral vision is more sensitive to motion in the dark, so a card
walking through its hidden rows at 03:00 is the one thing here that can wake somebody. It was
removed from the chair. The panel is lit **only** while the PC is on and logged in (invariant
3), so the dark room the rule protected has somebody awake at a machine in it — and the owner
watched the cards stop at 22:00, took it for a fault, and asked for the loop back.

So at night the panel dims and keeps moving, and `e2e/layout/check_night.py` asserts that
rather than the reverse. The value pulse also fires at night now, which the old rule had
suppressed entirely.

**The blackout is the one that still stops everything**, and it is untouched: offline or over
the thermal ceiling nobody can see the panel, and a moving card is only spending battery.

Only one rule reaches your animations now — the blackout's `animation-play-state: paused` —
and core only sets `data-night` while the panel is visible, so the two were never stacked
anyway. You owe the blackout rule the courtesy of not overriding `animation-play-state` on
something inside a dark panel.

The other half is yours, and it is taste:

- **Dim whatever you glow with.** Glow is a light source, and at night the room has no other
  one. `neon` halves two of its three `rgba()` glow properties under `:root[data-night]` and
  changes nothing else; `plain` has no glow and does nothing at all. The third is the alarm's,
  and the next bullet is why it is not in that list.
- **Do not build a second design.** The panel at night is the same panel read in the dark. A
  theme that also changed its colours, its sizes or its layout at 22:00 would be a surprise
  arriving nightly rather than a profile.
- **Leave the alarm alone.** If something on your panel means *this is wrong* — `neon`'s STALE
  badge — it exists to be seen from across a dark room, which is exactly the condition you are
  otherwise softening.

The backlight dims at the same moment and it is the bigger half of the effect by a long way:
`MainActivity` takes the window to `screenBrightness = 0.15f`, which is the one thing here no
stylesheet can reach. It reaches that decision by asking `NightWindow.java` the same question
about the same payload, so the two halves can disagree only for the seconds between a minute
boundary and the next refresh.

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

**And `context.resumed` is the other half of that, which is not optional if you read the DOM.**
The blackout *hides* `body`; it does not empty it. So on the first render after the PC has been
away all night, every row from last night is still mounted, every price in it differs from this
morning's, and a theme comparing the two flashes the entire panel at nine in the morning — the
one moment it is least useful. That render is the one core flags, and `neon` pulses nothing in
it. The same applies to any conclusion you draw by reading your own markup, not just to a
pulse: what is in there was not necessarily seen.

`check_pulse.py` asserts all four of those (nothing on a fresh mount, only the changed value on
a refresh, nothing at all on an identical payload, nothing on the way back from the blackout)
and that the pass is over inside ~300ms.
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

## The shortcut buttons are yours to draw and not yours to wire

`POST /action/{id}` mutes the PC's speakers and its microphone
([ADR 0015](adr/0015-the-panel-can-act-on-the-pc.md), T8.1). The buttons that
fire it are markup, so they are a theme's — and the wire is not.

### The contract, in full

```js
const wanted = shortcutsFor(payload.actions, words.tag);
// -> [{ id: 'mute-audio', label: 'SOUND', hint: 'Toggle mute' }, ...]

button.addEventListener('click', () => {
    const sent = DeskPanel.invoke(shortcut.id, (ok) => {
        // The outcome, later. Show it briefly and let it fade.
    });
    if (!sent) {
        // Refused outright: nothing was sent. Settle the button here, and
        // make settling idempotent -- the callback above has already run.
    }
});
```

That is all of it. A theme never sees a URL, a host, a port or a method.

### Which buttons exist is the PC's decision, not yours

`payload.actions` is the list of ids the server says it will accept — its
`actions` key in `config.toml`, already validated against the catalogue at
startup. Draw those, in that order, and draw **nothing** for anything else.

`shortcutsFor` is what enforces it: it drops an id this build has no word for,
which is the state a PC running ahead of the APK puts the panel in. A button
captioned `mute-everything` is one nobody can read, and a button nobody can
read is worse than the gap where one would be.

An empty list is normal and is the default. Render no buttons and leave the
strip empty; do not draw a placeholder.

### `invoke` returns false more often than you think

Core decides whether a press is possible at all, and a theme needs none of the
reasons:

| | |
|---|---|
| the PC is away | the buttons are dead offline. There is nothing to mute, the panel is black, and a press that was queued and fired on reconnect would mute the PC minutes after somebody pressed a button they could not see |
| the id is not in `payload.actions` | the server would answer 404 |
| there is no bridge | every browser. `js/mock.js` stubs one so buttons can be built without a phone |

`false` means **nothing was sent**. Settle the button yourself when you get it,
or it sits in its pressed state for ever.

**Make settling idempotent.** Core answers a refusal both ways — your callback
with `false`, and then `false` from `invoke` itself — so a settle written as
"run once per press" will otherwise run twice and leave two fade timers on one
button. And the callback can arrive with `false` for a press that *was* sent:
if the PC goes away before its result comes back, core abandons the press
rather than letting Java's answer, which is never coming, strand the button.
Both packaged themes keep a `settled` flag and cancel the previous fade on the
next press; copy that.

### Two things are drawn, and they have different lifetimes

```js
DeskPanel.invoke(id, (ok, state) => { ... });
// ok:    did the request work.  A brief acknowledgement, and it fades.
// state: 'muted' | 'unmuted' | 'unknown'.  What the PC's mixer now holds.
```

**The result fades. The state stays.** Getting those the same way round is the
whole of this section.

`state` is measured by the server, not inferred — a second read-only command
after the toggle ([ADR 0015](adr/0015-the-panel-can-act-on-the-pc.md)'s second
amendment) — so a theme may draw it. `neon` puts a cross on the icon; `plain`
says it in a word, because it has no pictures.

Three rules, and each of them is a way a button ends up lying about a live
microphone:

- **`unknown` is the resting state and it claims nothing.** A button nobody has
  pressed has not asked the PC anything. Draw the device and no cross.
- **Only a press that worked may move it.** A failure says so with the
  acknowledgement and leaves the state exactly where it was.
- **It is the last known state, not a live one.** Somebody at the keyboard can
  mute after the panel last asked. Say so where you can — both packaged themes
  put "when last asked" in the accessible name rather than letting the picture
  make a claim it cannot back.

Say the failure in **words as well as in colour**. The panel is read from
across a desk, and a red tint on its own is not a message — `plain` has no
palette to say it with at all, which is the honest test of whether a rule is
about the rule or about `neon`'s CSS.

`settle` has to be **idempotent**: core answers a refusal through the callback
*and* through `invoke`'s return value, so both arms can run for one press.
Cancel the previous press's fade timer too, or an acknowledgement that has not
finished yet fires part-way through the next press.

### A caption is optional; a legible icon is not

Neither packaged theme draws a caption any more. `shortcutsFor` still gives you
`label`, and both themes spend it on the **accessible name** instead — which is
what `title` shows and what a screen reader says — so the picture gets the room
and can be read across a desk. A theme is free to draw the word; it is not free
to draw a picture too small to identify, because the two buttons touch.

### 56px, on both axes, and it is not a matter of taste

This is a phone at arm's length with no pointer, and the two buttons touch. The
failure the size prevents is muting the microphone when you meant the speakers.
A theme may draw a button any way it likes and may not make it smaller than
this. Both packaged themes carry the rule in their own stylesheet.

Use a real `<button>`. It is focusable, it fires on a tap without waiting, and
it is announced as a button; a styled `<div>` with a click handler is none of
those.

### Rebuild them only when the set changes

The payload arrives once a minute and `actions` comes from a file a human
edits, so the buttons almost never change. Rebuilding them on every render
throws one away mid-press and loses the acknowledgement it was showing —
compare the ids you are about to draw against the ones you drew, and return
early. Both packaged themes do this with a one-line signature.

## The next meeting is yours to draw, and not yours to decide

The payload's `agenda` (T9.1, [ADR 0017](adr/0017-calendars-are-personal-data.md))
holds up to five events (three timed, two all-day) from the owner's calendars, already filtered on the PC —
no declined or cancelled event, no attendee, no body, and no `title` at all when
the owner turned titles off. Absent from an older server.

```js
const fields = agendaFields(payload.agenda, new Date(), words.tag);
// null: no agenda, or no calendar connected -- keep the box, set data-reserved
// { title, when, until, inProgress, failed }: strings, ready to draw
```

A theme with room for more than one line can ask for rows instead. Neon does,
and draws them as a quest tracker (a chip and a segmented bar on the first
event, the second on two lines, the third on one):

```js
const card = agendaRows(payload.agenda, new Date(), words.tag);
// null: as above
// { rows: [{ title, icon, live, when, aside, progress }], none, failed }
//   at most three rows, with or without a failure line under them -- how
//   many to draw is the theme's call (neon: three, or two beside a failure);
//   icon is 'live' | 'clock' | 'calendar', a name and never markup;
//   progress is 0..1 through a meeting in progress, else null
const lit = agendaSegments(row.progress, 10);   // floor: full means over
```

`agendaRows` ranks exactly as `agendaFields` does, so its first row is always
the event `agendaFields` would have shown. `?agenda=live` in the mock starts the
first meeting 35 minutes ago, for the chip and the bar.

- **Which event, and what the countdown says, is `agendaFields`'s decision.**
  An event in progress beats the next one; a timed event later today beats an
  all-day one; ties break the same way every time, so the line never flickers
  between two meetings in one minute. A theme that sorted the events itself
  would get one of those wrong.
- **The phone's clock decides**, like the night window. The PC sends instants,
  never "in 25 min", so redraw from the payload you already have whenever the
  minute turns — from `tick`, never by waiting for the next payload, which
  arrives on a clock of its own.
- **`failed` is a line, not a blank card.** In the payload it is a list of
  `{source, reason}`: `reconnect` when the login was refused or never run, so
  only the owner can fix it on the PC, and `unavailable` when the provider or
  the network is down and the server retries by itself. `agendaFields` turns it
  into one string — `microsoft/work: reconectar · google/work: indisponível` —
  and reads a bare string entry as `reconnect`. The other account's meeting is
  still the next meeting, and the rest of the panel is none of its business.
  With a failure and no event, `when` is empty rather than "nada à vista": the
  meeting may be in the calendar the PC could not read.
- **Nothing in it may wrap.** A title is whatever somebody typed into a
  calendar. Ellipsise every line, inside an element of its own rather than on
  the section: an ellipsis on the section is content wider than its box, and
  the harness reports it as a clipped card — correctly, since it cannot tell
  one from the other. `e2e/layout/stress.js` carries the widest countdown at full
  size ("amanhã 09:00"), a very long title and the longest failure line;
  `e2e/layout/agenda.js` carries a meeting in progress that ends tomorrow,
  which `agendaRows` gives no time-left so that "até amanhã 10:00" fits, and
  two events behind it: the tallest the card gets. `agenda-failed.js` is the
  same three with a failure line, the case neon draws with two compact rows.

## Whether the market is open is the PC's answer

`payload.b3Open` is `false` while B3's session is shut, `true` while it runs,
and absent from an older server. The window follows US daylight saving, not
Brazil's clock (`server/market_hours.py`), so it is decided on the PC and never
from the phone's clock the way the night window is.

```js
const closed = marketClosed(payload);   // true only on an explicit false
// words.marketClosed: FECHADO / CLOSED
```

Draw the word beside the B3 title while `closed` is true, and nothing
otherwise. **Absent is not closed**: a theme that tested `!payload.b3Open` would
say CLOSED all day on a PC that has not been updated. `?b3=closed` holds the
label on in a browser, and `e2e/layout/stress.js` carries it.

## Checking it

```bash
node --test "web/test/**/*.test.js"          # format.js, which you did not change
python e2e/layout/check_layout.py --theme <name>
python e2e/layout/check_blackout.py --theme <name>
python e2e/layout/check_scroll.py --theme <name>
python e2e/layout/check_pulse.py --theme <name>    # only if your theme pulses
python e2e/layout/check_actions.py --theme <name>  # the shortcut contract above
```

The layout check drives a real browser at 872x392 — the phone's actual
viewport — and runs four payloads: the served one from `mock.js`; the widest
case the panel can legitimately be asked to show (`e2e/layout/stress.js`: the
longest city, the longest weather label, a negative temperature, a six-figure
price beside a sub-1 one, a ticker far longer than five characters, and the
STALE badge shown); a weather code with no glyph, where a theme that draws the
condition as a word must fit that word in the picture's slot
(`e2e/layout/unknown.js`); and more rows than any card can fit
(`e2e/layout/overflow.js`). The second is the one that fails on sizes. The
fourth is the only pass that requires something to *happen* rather than
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

`check_actions.py` is the one that checks the section above, and it is the only check here that
presses something: it replaces the native bridge with a recorder, delivers the payloads a PC
with one action, two actions and none would send, and asserts what your buttons did. The right
ids in the PC's order, nothing drawn for an id this build has no word for, 56px on both axes, a
real `<button>`, an id and nothing url-shaped reaching the bridge, a failure said in words as
well as in colour, and **nothing sent while the PC is away**. It expects the buttons to exist,
so it is not optional the way `check_scroll` and `check_pulse` are: a theme that draws no
shortcuts fails it, which is the point.

`check_blackout.py` is the other half, and it is the one your theme can fail without looking
wrong: it drives the page dark on both causes and asserts that nothing is drawn while it is,
that the payload you missed arrives on the way back, and that `#clock` holds a time before any
payload at all. If you put `visibility: visible` on something, this is what tells you.

Then look at it on the device, because the harness cannot: Android resolves
`sans-serif-condensed` to Roboto Condensed and the desktop falls back to
something wider, so measured text widths are a conservative estimate rather
than the truth.
