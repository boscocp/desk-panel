// Pure formatting/labeling helpers for the panel UI.
//
// No DOM access here on purpose: node:test has no DOM, so this file is the
// boundary between "logic" (testable, lives here) and "rendering" (thin,
// lives in app.js). See docs/adr/0006-no-framework-web-layer.md.
//
// Loaded two ways with no build step:
//   - Browser: index.html includes this as a plain, non-module <script> before
//     app.js. Top-level function declarations in a non-module script become
//     properties of the global object, so app.js can call them directly.
//   - Node: web/test/*.test.js requires this file; the CommonJS export below
//     makes that work without touching the (nonexistent) global object.

const CURRENCY_SYMBOLS = {
    BRL: 'R$',
    USD: '$',
    EUR: '€',
};

// value: number, currency: one of CURRENCY_SYMBOLS, defaults to plain number.
function formatPrice(value, currency) {
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return '--';
    }
    const symbol = CURRENCY_SYMBOLS[currency] || '';
    // Two decimals is right for equities and FX, and wrong for the cheap end
    // of crypto: a coin at 0.00081 renders as 0.00, so its price and every
    // movement in it disappear. Below 1, widen the window instead.
    const small = value !== 0 && Math.abs(value) < 1;
    const formatted = value.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: small ? 8 : 2,
    });
    return `${symbol}${formatted}`;
}

// rate: number. An FX rate, which is not a price and does not want
// formatPrice's rules.
//
// Exchange rates are quoted to four decimal places by convention, and the
// convention exists because both of formatPrice's branches get them wrong.
// Above 1 it truncates to two, so USD/BRL at 5.1434 rendered as R$5.14 and
// threw away digits a rate is actually read for. Below 1 it opens the window
// to eight, which is meant for a coin at 0.00081 and turned CNY/BRL into
// R$0.76749533 -- a number so wide it pushed its own label out of the column.
//
// Three decimals, and magnitude-independent, so every row in the card is the
// same width whether the rate is 5.143 or 0.767.
function formatRate(rate, currency) {
    if (typeof rate !== 'number' || !Number.isFinite(rate)) {
        return '--';
    }
    const symbol = CURRENCY_SYMBOLS[currency] || '';
    const formatted = rate.toLocaleString('en-US', {
        // Three and three. A minimum of two made the comment above false: a
        // rate that happened to land on two decimals rendered narrower than
        // its neighbours, and "same width whatever the magnitude" was the
        // whole point of having a separate formatter.
        minimumFractionDigits: 3,
        maximumFractionDigits: 3,
    });
    return `${symbol}${formatted}`;
}

// c: a temperature in Celsius, or null/undefined when the upstream had none.
//
// The server returns null rather than 0 on purpose -- zero is a real reading
// in most of the world, so a zero standing in for "no data" is a lie the panel
// cannot detect. That only works if the page renders the null as an absence,
// and it did not: the weather line interpolated it straight into a template
// and produced "São Paulo: 24°C (null-null°C)". providers_openmeteo's own
// docstring claimed this function existed before it did.
function formatTemp(c) {
    if (typeof c !== 'number' || !Number.isFinite(c)) {
        return '--';
    }
    // One decimal, because the current reading has one and the daily range
    // does too; rounding here would make 15.5 and 15.6 the same number.
    return `${Math.round(c * 10) / 10}`;
}

// pair: "USD/BRL". quote: the currency the whole card is denominated in.
//
// Drops the quote half when it is the same for every row, because then it is
// a property of the card rather than of the line: the card already says R$ on
// every value, and "USD/BRL" spends a third of the label column repeating it.
// A pair quoted in anything else keeps both halves, so a future EUR/USD row
// still says what it is.
function formatPair(pair, quote) {
    if (typeof pair !== 'string') {
        return '';
    }
    const [base, counter] = pair.split('/');
    if (!counter) {
        return pair;
    }
    return counter === quote ? base : pair;
}

// values: array of numbers, oldest first. width/height: the SVG viewBox.
//
// Returns the `d` of a polyline through the series, scaled to fill the box,
// or '' when there is nothing to draw. Pure, and it is the whole of the
// sparkline: app.js only wraps the string in an <svg>, which is what keeps
// the drawing testable without a DOM.
//
// Two decisions worth naming, because both are about not lying with a
// picture. The series is scaled to its own min and max rather than to zero,
// so the line uses the full height and shows the shape of the movement -- a
// currency that moved 0.4% would otherwise be a flat line, which is true of
// the magnitude and useless about the trend. And a series with no range at
// all is drawn as a centred flat line rather than divided by zero.
function sparklinePath(values, width, height) {
    if (!Array.isArray(values)) {
        return '';
    }
    const points = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
    if (points.length === 0) {
        return '';
    }

    // Half the stroke would be clipped at the extremes without an inset, so
    // the line is drawn into a slightly shorter box than the one it sits in.
    const inset = 1;
    const usable = Math.max(0, height - inset * 2);

    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = max - min;

    const x = (i) => (points.length === 1 ? width : (i / (points.length - 1)) * width);
    const y = (value) => (range === 0
        ? inset + usable / 2
        // SVG y grows downward, so the higher value gets the smaller y.
        : inset + (1 - (value - min) / range) * usable);

    if (points.length === 1) {
        // One point is a value, not a trend: draw it as a flat line across the
        // box so the row still has the same shape as its neighbours.
        return `M0,${round2(y(points[0]))} L${width},${round2(y(points[0]))}`;
    }

    return points
        .map((value, i) => `${i === 0 ? 'M' : 'L'}${round2(x(i))},${round2(y(value))}`)
        .join(' ');
}

// Two decimals is plenty for a 56px box and keeps the path short -- this
// string is rebuilt for every row on every refresh.
function round2(n) {
    return Math.round(n * 100) / 100;
}

// --- The slow scroll, when a card holds more rows than it can show (T6.6) ---
//
// The panel is exactly one screen and every card clips its own content, which
// is what stops a sixth ticker arriving from server config pushing a section
// off the bottom edge. The cost was that the sixth ticker was *invisible* --
// not truncated, not marked, simply absent, with nothing on the panel saying
// so. These two decide when a card is allowed to move instead.
//
// Both are pure and both count rows rather than pixels: the measuring is the
// theme's job, because only the theme knows what a row looks like, and the
// decision is here, because a decision is the thing worth testing.

// rowCount: how many rows the card was given. visibleRows: how many of them
// fit inside it. Returns how many are hidden -- zero when they all fit, which
// is the answer that means "do not move".
//
// Anything unusable counts as no overflow rather than as some. A card that
// started scrolling because a measurement came back NaN would be motion in
// the corner of someone's eye all day, with no way to tell what it was for.
function overflowsBy(rowCount, visibleRows) {
    if (!Number.isFinite(rowCount) || !Number.isFinite(visibleRows)) {
        return 0;
    }
    return Math.max(0, Math.ceil(rowCount) - Math.floor(visibleRows));
}

// How long the card takes to walk past one row.
//
// **Sixteen, which is a quarter of the speed T6.6 shipped** (T6.9). Four
// seconds a row was chosen against a card that walked down and came back; the
// card now goes round and round in one direction for as long as the panel is
// on, and a movement that never ends is a movement the eye keeps returning to
// at four times that speed. At sixteen it is slow enough to be scenery and
// still gives up a row every sixteen seconds, so the whole of a nine-row card
// is on screen inside two and a half minutes.
//
// It is the *whole* list that moves now, not just the hidden part, so a pass
// is rowCount * this rather than hidden * this. The two agree about speed in
// pixels per second, which is the thing a reader actually experiences, and
// that is why the number could be compared with the old one at all.
//
// There is no companion fraction any more. T6.6's keyframes held at each end
// so the top and bottom of the card could be read, so the cycle was longer
// than the travel and format.js had to be told by how much; a loop has no
// ends to hold at. `--scroll-moving-fraction` is gone from both themes with
// it.
const SCROLL_SECONDS_PER_ROW = 16;

// Below this, a card does not move however the row arithmetic came out.
//
// The review of T6.6 found the case this exists for, and it only happens on the
// phone. `clientHeight` and `scrollHeight` are integers; the device lays out at
// a device pixel ratio of 2.75, so a card whose rows exactly fill it can report
// 102px of content in a 101px window. That is one hidden row by every count
// above, and a travel of one pixel: the card would declare a scroll, hold a
// compositor layer, and twitch a pixel back and forth every seventeen seconds
// for as long as the panel is on. Nothing in e2e/layout would fail -- 1px is a
// real overflow as far as the harness can tell -- so it would have shipped and
// been visible only from the chair.
//
// Four pixels, which is comfortably above the two a pair of integer roundings
// can invent and far below the twenty-odd a genuinely hidden row is worth.
const SCROLL_MIN_TRAVEL_PX = 4;

// travelPx: how far the card would actually move, which only the theme can
// measure. Pure and separate from scrollPlan because it is a different
// question -- scrollPlan counts rows, this one asks whether the pixels those
// rows came out to are worth moving for.
function worthScrolling(travelPx) {
    return Number.isFinite(travelPx) && travelPx >= SCROLL_MIN_TRAVEL_PX;
}

// Returns null when nothing should move, or {hidden, seconds} when it should.
// null rather than {hidden: 0}: "do not scroll" is a different answer from
// "scroll by nothing", and a caller that has to check a field to tell them
// apart eventually forgets to.
//
// `hidden` is still what decides *whether* to move -- a card showing every row
// it has must not -- and it no longer decides how far or how long. The card
// goes round: it walks the full list once per pass and the seam is invisible
// because the theme has drawn the list twice (T6.9). So the pass is rowCount
// long, and a card with one row hidden out of nine takes the same two and a
// half minutes as one with five hidden, because both are showing the same
// nine rows at the same speed.
function scrollPlan(rowCount, visibleRows, secondsPerRow) {
    const hidden = overflowsBy(rowCount, visibleRows);
    if (hidden === 0) {
        return null;
    }
    const perRow = Number.isFinite(secondsPerRow) && secondsPerRow > 0
        ? secondsPerRow : SCROLL_SECONDS_PER_ROW;
    return { hidden: hidden, seconds: Math.round(rowCount * perRow * 100) / 100 };
}

// pct: number (e.g. 1.23 for +1.23%). Sign, one decimal, percent sign.
// Zero is shown without a sign, matching changeClass's "flat" bucket.
function formatChange(pct) {
    if (typeof pct !== 'number' || !Number.isFinite(pct)) {
        return '--';
    }
    if (pct === 0) {
        return '0.0%';
    }
    const sign = pct > 0 ? '+' : '-';
    return `${sign}${Math.abs(pct).toFixed(1)}%`;
}

// pct: number. "up" / "down" / "flat" for styling.
function changeClass(pct) {
    if (typeof pct !== 'number' || !Number.isFinite(pct) || pct === 0) {
        return 'flat';
    }
    return pct > 0 ? 'up' : 'down';
}

// WMO weather interpretation codes (open-meteo, same table brapi's weather
// proxy will pass through) mapped to a short human label.
const WEATHER_LABELS = {
    0: 'Clear sky',
    1: 'Mainly clear',
    2: 'Partly cloudy',
    3: 'Overcast',
    45: 'Fog',
    48: 'Rime fog',
    51: 'Light drizzle',
    53: 'Drizzle',
    55: 'Dense drizzle',
    61: 'Light rain',
    63: 'Rain',
    65: 'Heavy rain',
    71: 'Light snow',
    73: 'Snow',
    75: 'Heavy snow',
    80: 'Light showers',
    81: 'Showers',
    82: 'Violent showers',
    95: 'Thunderstorm',
    96: 'Thunderstorm, hail',
    99: 'Thunderstorm, heavy hail',
};

function weatherLabel(code) {
    return WEATHER_LABELS[code] || 'Unknown';
}

// minC/maxC: the day's low and high, or null when the upstream had none.
//
// This exists because joining two temperatures with a hyphen is ambiguous the
// moment one of them is negative: the stress payload rendered `(-12-42°C)`,
// which is not a styling problem but a string nobody can parse by eye. A
// separator that cannot be read as a sign fixes it, and there is no separator
// made of `-` that can be trusted to do that -- so the join is ` / `.
//
// The degree signs are here rather than in the theme because the card no
// longer writes a sentence around this: each line is its own statement now,
// and `18 / 27` with the unit somewhere else is a worse thing to read.
function formatRange(minC, maxC) {
    const low = formatTemp(minC);
    const high = formatTemp(maxC);
    if (low === '--' && high === '--') {
        return '--';
    }
    // The unit goes on the numbers and not on the dashes. `--°` is a
    // temperature of nothing-degrees, which is the same kind of string this
    // function exists to stop -- and a partial upstream failure is exactly when
    // the panel most needs to be read at a glance rather than puzzled over.
    const unit = (t) => (t === '--' ? t : `${t}°`);
    return `${unit(low)} / ${unit(high)}`;
}

// The WMO codes above, collapsed to the small closed set a picture can
// actually distinguish at 40px. Returns a name, never markup: the theme owns
// what a cloud looks like, and this file owns no DOM.
//
// 'unknown' is a real member of the set and not an error. A code outside the
// table is a code open-meteo added after this was written, and the label
// beside the glyph still says what it is -- so the honest picture is no
// picture, which is what the theme draws for this name.
const WEATHER_GLYPHS = {
    0: 'clear', 1: 'clear',
    2: 'cloudy', 3: 'cloudy',
    45: 'fog', 48: 'fog',
    51: 'rain', 53: 'rain', 55: 'rain',
    61: 'rain', 63: 'rain', 65: 'rain',
    80: 'rain', 81: 'rain', 82: 'rain',
    71: 'snow', 73: 'snow', 75: 'snow',
    95: 'storm', 96: 'storm', 99: 'storm',
};

function weatherGlyph(code) {
    return WEATHER_GLYPHS[code] || 'unknown';
}

// Above this, the panel says so. Lithium ageing is dominated by heat, and the
// point of putting a thermometer on a device that lives on a desk all day is to
// see the number climb before the back cover does (T5.4, ADR 0008).
//
// 40 is warm for a phone on a charger and not yet a fault, which is why the
// treatment is a colour rather than a badge: something to notice on the way
// past, not something to act on at once.
const BATTERY_WARN_C = 40;

// battery: {level, tempC, charging} from the payload, or undefined before the
// first broadcast. Returns the whole corner line, or '' when there is nothing
// worth saying -- app.js renders nothing at all for '', rather than an empty
// box with a label in it.
//
// "BAT" rather than a card title: T5.4 demotes this from a card to a line, so
// the line has to say what it is on its own. Three characters is the cheapest
// way to do that.
function formatBattery(battery) {
    if (!battery || typeof battery.level !== 'number' || !Number.isFinite(battery.level)) {
        return '';
    }
    const parts = [`BAT ${Math.round(battery.level)}%`];

    // Reuses formatTemp, so an absent temperature is drawn as an absence here
    // exactly as it is in the weather line. The native side leaves the key out
    // rather than sending a zero, for the same reason the server does.
    const temp = formatTemp(battery.tempC);
    if (temp !== '--') {
        parts.push(`${temp}°C`);
    }

    // Only the interesting half is spelled out. On this desk the phone is
    // powered from the PC's USB, so charging is the resting state and saying so
    // every second of every day would spend the line's width on no information;
    // "unplugged" is the condition that is worth a word, because it means the
    // panel is now running the battery down (ADR 0014).
    if (battery.charging === false) {
        parts.push('unplugged');
    }
    return parts.join(' · ');
}

// Red, and the last colour before the screen goes out: ThermalState.BLANK_AT_C
// blanks the panel at 45 (T5.5, ADR 0012), so this leaves two degrees of
// warning at the rate a phone in a stand actually climbs -- minutes, not
// seconds.
//
// **This number and BLANK_AT_C are one decision spread across two languages,
// with nothing in the build to tie them together.** There is no code path from
// Java into these files -- web/ has no build step, by design (ADR 0006) -- so
// the link is this comment and its twin in ThermalState.java. Lower BLANK_AT_C
// below this without changing this, and the panel blanks before it has ever
// turned red: the ramp that ADR 0012 calls its decisive piece stops existing,
// and every test in the repo stays green.
//
// The ramp is the piece that makes the blanking legible. A black panel already
// means one thing here, "the PC is off", and that is the whole product; a
// second cause of black that arrived with no warning would be read as the PC
// having died or the app having crashed. By the time the screen blanks it has
// been visibly reddening, so the dark panel is never ambiguous.
const BATTERY_HOT_C = 43;

// tempC: number, or anything else. Returns which band the temperature is in:
// 'normal', 'warm' at the T5.4 warning point, 'hot' approaching the thermal
// cutoff. app.js turns that into a class; this file owns no DOM.
//
// A band rather than a boolean, which is what this replaced: two colours need
// two thresholds, and a pair of booleans that must not both be true is a state
// machine written in the wrong place.
//
// An absent or unusable temperature is 'normal', never 'hot'. A panel that
// reddened because a sensor stopped answering would teach its owner to ignore
// the colour, which costs more than the reading is worth.
function tempClass(tempC) {
    if (typeof tempC !== 'number' || !Number.isFinite(tempC)) {
        return 'normal';
    }
    if (tempC >= BATTERY_HOT_C) {
        return 'hot';
    }
    return tempC > BATTERY_WARN_C ? 'warm' : 'normal';
}

// now: Date. start/end: "HH:MM" as shipped in server/config.json
// (night_start / night_end) and in the payload's night:{start,end} — a bare
// hour integer is accepted too. Returns false if either bound is unparseable,
// so a malformed config leaves the panel in its day profile rather than dark.
//
// Minutes are honoured: "22:30" must not round down to 22:00, or the panel
// dims half an hour early every night.
function minutesOfDay(bound) {
    if (typeof bound === 'number' && Number.isInteger(bound) && bound >= 0 && bound <= 23) {
        return bound * 60;
    }
    if (typeof bound !== 'string') {
        return null;
    }
    const match = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(bound.trim());
    if (!match) {
        return null;
    }
    return Number(match[1]) * 60 + Number(match[2]);
}

function isNight(now, start, end) {
    const from = minutesOfDay(start);
    const to = minutesOfDay(end);
    if (from === null || to === null || from === to) {
        return false;
    }
    const at = now.getHours() * 60 + now.getMinutes();
    if (from < to) {
        return at >= from && at < to;
    }
    // The window wraps midnight, e.g. 22:00 -> 07:00.
    return at >= from || at < to;
}

// --- Burn-in mitigation: the panel never sits still for long (T6.2) ---------
//
// This device is an AMOLED showing one unchanging layout for every hour the PC
// is on. That is the burn-in case ADR 0008 names: the clock's glyph edges, the
// card borders and the four card titles are lit in exactly the same pixels all
// day, and an OLED pixel ages by how long it has been lit. The ground is
// already #000000 -- those pixels are physically off and cost nothing -- so
// what is left to protect is the ink, and the cheap way to protect it is to
// keep moving it.
//
// The decision is here rather than in a theme because it is a promise about
// hardware, exactly as the blackout beside it is (css/style.css, ADR 0005), and
// a theme that forgot it would look perfectly fine and quietly etch the
// display. The theme owes it nothing at all: core applies the offset to
// whatever the theme put in the body. What is genuinely a decision -- how far,
// how often, and in what order -- is a pure function of the clock, which is
// what makes it testable without watching a screen for half an hour.

// How far the panel is allowed to travel, in CSS px.
//
// Small enough not to be noticeable and large enough to matter, which is the
// whole of the tuning problem. Antialiased text has one or two pixels of edge,
// so four is enough to put a glyph's edge somewhere it has not been; and four
// against the neon theme's 10px body padding (12px on plain) leaves the panel
// comfortably inside its own margin at every offset, which is what stops the
// shift turning into a layout bug.
const BURN_IN_AMPLITUDE_PX = 4;

// How long the panel holds one offset.
//
// Four minutes: long enough that the step is not something you catch out of
// the corner of your eye every time you look up, short enough that the ink
// has moved fifteen times an hour.
const BURN_IN_STEP_MINUTES = 4;

// The cycle, and every number in it is negative or zero. **That is not a
// stylistic choice and it must stay true.**
//
// A transform that pushes content past the bottom or right edge of the
// document adds to the page's scrollable overflow; one that pulls it up and to
// the left does not, because content above and left of the scroll origin is
// unreachable rather than scrollable. The panel is exactly one screen and
// `check_layout.py`'s first question is "does the document scroll" -- so
// shifting down or right would either fail that check or, worse, make the page
// genuinely scrollable and give a card somewhere to hide a row. Up and left
// costs nothing: the ground behind the panel is black either way.
//
// Seven positions rather than a rectangle's four, and in an order that never
// takes two short steps in a row: a four-cycle settles into a shape the eye
// learns, and a slow raster leaves each position adjacent to the last, which
// is the least relief per move.
//
// Two properties of the table, both asserted in web/test/format.test.js rather
// than only claimed here -- an earlier version of this comment promised a third
// that seven entries cannot have, which is what earned the test:
//
//   - every value in [-4, 0] appears in each axis, so the whole of the band is
//     used and not just its corners,
//   - each axis sums to -14, which is a mean of exactly -2: the middle of the
//     band, so the panel has no standing offset in either direction.
const BURN_IN_OFFSETS = [
    { x: 0, y: 0 },
    { x: -3, y: -1 },
    { x: -1, y: -4 },
    { x: -4, y: -3 },
    { x: -2, y: -2 },
    { x: 0, y: -4 },
    { x: -4, y: 0 },
];

// now: Date. Returns {x, y} in CSS px, both <= 0.
//
// A pure function of the clock, and it has to stay one: js/host.js calls it
// once a second and writes the result to two custom properties, so a value
// that drifted with anything but the time would rewrite the transform under a
// panel that had not moved.
function offsetFor(now) {
    // Duck-typed, and `instanceof Date` was the first cut. It is wrong in a way
    // that is invisible: `instanceof` compares against *this realm's* Date, so
    // a Date built anywhere else -- an iframe, a test harness driving the page
    // from outside, e2e/layout/check_layout.py's Marionette sandbox -- is not
    // an instance of it, and the guard answered the origin for every clock the
    // sweep handed it. Seven positions, all (0,0), and a burn-in check that
    // reported the feature working perfectly while measuring one position
    // seven times. Nothing about it looked wrong; the sweep's own "the panel
    // never moves" assertion is what caught it.
    //
    // In production the Date comes from js/app.js, one realm away from nothing.
    // The point is that the failure was silent, and this is one line.
    const time = now && typeof now.getTime === 'function' ? now.getTime() : NaN;
    if (!Number.isFinite(time)) {
        return { x: 0, y: 0 };
    }
    // Counted from the epoch and not from midnight, and the difference is the
    // whole reason this is not a rota. A day is 360 steps against a cycle of
    // seven; 360 mod 7 is 3, so the phase advances three positions a night and
    // the panel is not where it was at this time yesterday until the seventh
    // day. Counting from midnight was the first cut and it fails the thing the
    // task file asks for in one sentence: the PC is on for roughly the same
    // hours every day, so every offset would land under the same glyphs at the
    // same hour, for ever -- a cycle that has itself become a pattern, which is
    // the trap rather than the mitigation.
    //
    // The modulo is written twice because a Date before 1970 gives a negative
    // step, and JavaScript's % keeps the sign: `-1 % 7` is -1, which indexes
    // nothing. Nobody will run this panel in 1969; a table read off the end is
    // still `undefined.x` a line later, which is the kind of failure that
    // happens once and is never explained.
    const size = BURN_IN_OFFSETS.length;
    const step = Math.floor(time / (BURN_IN_STEP_MINUTES * 60000));
    const offset = BURN_IN_OFFSETS[((step % size) + size) % size];
    // A copy, not the table's own entry. The caller is outside this file, and
    // one that wrote to what it was handed -- rounding it, clamping it, zeroing
    // it for a frame -- would not fix a position, it would delete that position
    // from the cycle for the life of the page.
    return { x: offset.x, y: offset.y };
}

// The whole cycle, described, for anything that has to visit every offset
// rather than wait for one.
//
// It exists for `e2e/layout/check_layout.py`. Without it that harness measures
// the panel at whichever offset the wall clock happened to land on, which
// means the worst case is measured one run in seven and a layout that only
// fails at (-4,-3) is a check that fails on a Tuesday. With it the harness
// drives the panel through every position and measures each -- and a shift
// that pushed a card off the edge would be a certainty rather than a chance.
//
// `offsets` is the cycle in the order the panel walks it; which one is showing
// right now is the clock's business, so a caller that wants all of them steps
// the clock `stepMinutes` at a time, `offsets.length` times, from wherever it
// happens to start. It gets every position, in a rotation of this order.
//
// Copies, because the caller is outside this file and the table is not its to
// edit.
function burnInSchedule() {
    return {
        stepMinutes: BURN_IN_STEP_MINUTES,
        amplitudePx: BURN_IN_AMPLITUDE_PX,
        offsets: BURN_IN_OFFSETS.map((o) => ({ x: o.x, y: o.y })),
    };
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        formatPrice, formatRate, formatPair, formatTemp, formatChange, changeClass,
        weatherLabel, weatherGlyph, formatRange, WEATHER_LABELS,
        isNight,
        offsetFor, burnInSchedule,
        BURN_IN_OFFSETS, BURN_IN_STEP_MINUTES, BURN_IN_AMPLITUDE_PX,
        overflowsBy, scrollPlan, worthScrolling,
        SCROLL_SECONDS_PER_ROW, SCROLL_MIN_TRAVEL_PX,
        sparklinePath,
        formatBattery, tempClass, BATTERY_WARN_C, BATTERY_HOT_C,
    };
}
