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

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        formatPrice, formatRate, formatPair, formatTemp, formatChange, changeClass,
        weatherLabel, isNight,
        sparklinePath,
        formatBattery, tempClass, BATTERY_WARN_C, BATTERY_HOT_C,
    };
}
