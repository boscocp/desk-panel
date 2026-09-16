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
    const formatted = value.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
    return `${symbol}${formatted}`;
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
    module.exports = { formatPrice, formatChange, changeClass, weatherLabel, isNight };
}
