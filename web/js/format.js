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
// above, and the card would declare a scroll, hold a compositor layer, and move
// for as long as the panel is on -- to reveal a pixel. Nothing in e2e/layout
// would fail, because 1px is a real overflow as far as a measurement can tell,
// so it would have shipped and been visible only from the chair.
//
// **T6.9 made the price of getting this wrong much higher, and the review of
// T6.9 is what noticed.** Under T6.6 a card walked as far as its hidden pixels
// and came back, so five pixels of phantom overflow bought five pixels of
// twitch. The card now goes round: any overflow at all, however small, walks
// the *entire list* past the window for ever. Four pixels was chosen as
// "comfortably above the two a pair of integer roundings can invent and far
// below the twenty-odd a genuinely hidden row is worth" -- deliberately letting
// 5-20px through, because under the old design they were cheap. They are not
// cheap any more.
//
// So the floor is a fraction of a row rather than a flat count of pixels, which
// is what the sentence above was reaching for all along. Half a row is past
// anything two integer roundings can invent at any dpr, and well under one
// genuinely hidden row. The flat four stays as the floor for a caller that
// cannot measure a row, which is the only case where a bare pixel count is
// still the best available answer.
const SCROLL_MIN_TRAVEL_PX = 4;
const SCROLL_MIN_HIDDEN_ROWS = 0.5;

// hiddenPx: how much of the list is out of sight, which only the theme can
// measure. rowHeightPx: what one row of it is worth, for turning that into a
// judgement rather than a number.
//
// Pure and separate from scrollPlan because it is a different question --
// scrollPlan counts rows and says whether any are hidden, and this asks whether
// what they came out to in pixels is worth putting a card in permanent motion
// for.
function worthScrolling(hiddenPx, rowHeightPx) {
    if (!Number.isFinite(hiddenPx) || hiddenPx < SCROLL_MIN_TRAVEL_PX) {
        return false;
    }
    if (!Number.isFinite(rowHeightPx) || rowHeightPx <= 0) {
        return true;
    }
    return hiddenPx >= rowHeightPx * SCROLL_MIN_HIDDEN_ROWS;
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

// --- Every word the panel shows (T6.11) -------------------------------------
//
// The panel stands on a desk in Brazil and said "Light drizzle". The rule for
// the rest of this repository is English everywhere -- code, comments, docs,
// commit messages -- and none of that is what a person reads from a chair two
// feet away, which is the one category that has to be in their language.
//
// **The language is config, exactly like the theme** (T3.12, ADR 0013). It
// rides the payload from `server/config.toml` and defaults to pt-BR, so
// changing it is editing a file on the PC and never a rebuild of the APK. The
// device's own locale is deliberately *not* what decides: a phone in a stand
// running the system in one language is not evidence about who is looking at
// the panel, and there would be no way to ask for the other one.
//
// A table per language rather than a lookup per string. Two reasons, and the
// second is the one that matters: a missing key in a table is visible the
// moment the table is read next to its neighbour, and a table is the shape a
// third language is added in without touching a single call site.
//
// WMO weather interpretation codes (open-meteo, the same table brapi's
// weather proxy passes through) mapped to a short human label. Short is the
// constraint: the weather card gives the condition one line at 20px, and
// "Trovoada com granizo forte" is already the widest thing on the panel.
const LANGUAGES = {
    'pt-BR': {
        // The tag the table answers to, carried inside it so that a caller
        // holding the table can hand it to Intl -- `toLocaleDateString` takes
        // a tag and not a vocabulary, and the resolved tag is the one thing
        // `strings` knows that its caller does not.
        tag: 'pt-BR',
        unknown: 'Desconhecido',
        // Never drawn: the accessible name of the rain drop beside the city.
        rainChance: 'Chance de chuva',
        // The eight phases, in the order a lunation visits them. The panel
        // draws a shape and these are its accessible name -- eight glyphs
        // cannot tell a waxing crescent from a waning one at 24px, and the
        // difference is the half somebody can check by looking up.
        moon: {
            'new': 'Lua nova',
            'waxing-crescent': 'Lua crescente',
            'first-quarter': 'Quarto crescente',
            'waxing-gibbous': 'Crescente gibosa',
            'full': 'Lua cheia',
            'waning-gibbous': 'Minguante gibosa',
            'last-quarter': 'Quarto minguante',
            'waning-crescent': 'Lua minguante',
        },
        // "DEFASADO", not "DESATUALIZADO", and the difference is five
        // characters the badge does not have. It is drawn in the top corner
        // of the weather card, where the card's own title already is: at
        // thirteen characters the badge lands on top of TEMPO and both words
        // become unreadable. Defasado is what a quote that is behind the
        // market is called in Portuguese anyway, which is exactly what this
        // badge means.
        stale: 'DEFASADO',
        // Beside the B3 title while the exchange is shut (server/market_hours.py).
        marketClosed: 'FECHADO',
        // "na bateria" rather than "desconectado", which in Portuguese reads
        // first as a network having dropped -- the wrong alarm entirely on a
        // panel whose other states are about the PC being away.
        unplugged: 'na bateria',
        // `agenda` names a card that holds nothing yet: the reserved box T9.1
        // will fill with the next meeting (T6.12). The word is here rather
        // than in the theme for the same reason every other title is -- a
        // panel in another language is a restart of the PC's server, never a
        // rebuild -- and having it here is what makes the key-set test above
        // ask the next language for it too.
        titles: { quotes: 'B3', fx: 'CÂMBIO', crypto: 'CRIPTO', weather: 'TEMPO',
                  agenda: 'AGENDA' },
        // The shortcut buttons (T8.2). Keyed by the server's action id, which
        // is the same string on both sides of the wire and in both languages —
        // the id is an identifier, the value is what a person reads.
        //
        // These are the button's accessible name and its visible caption both,
        // so they are the shortest thing that is still unambiguous: two
        // buttons sit next to each other and a mis-tap mutes the wrong device.
        // "MIC" over "MICROFONE" for the same reason "DEFASADO" is not
        // "DESATUALIZADO" — the box is 56px and the word has to fit in it.
        actions: { 'mute-audio': 'SOM', 'mute-mic': 'MIC' },
        // Said to a screen reader and used as the title attribute, because
        // the caption alone does not say the button *toggles*.
        actionHint: 'Alternar mudo',
        actionFailed: 'falhou',
        // Said only to a screen reader, and only after the PC has reported --
        // the picture carries it for everybody else. "Mudo agora" rather than
        // "mudo": the panel knows the last state the PC gave it and not a live
        // one, and the word has to carry that or the sentence is a claim the
        // page cannot back.
        actionMuted: 'mudo na última vez',
        actionUnmuted: 'com som na última vez',
        // The AGENDA card (T9.1). Short on purpose, like everything that sits
        // in a card: the countdown is read from across the desk and the card
        // is a third of the right-hand column. "reconectar" is the one word
        // that asks the owner to do something, and it says what -- run the
        // login again on the PC -- rather than an error nobody can act on.
        agenda: {
            in: 'em',
            now: 'agora',
            until: 'até',
            today: 'hoje',
            tomorrow: 'amanhã',
            allDay: 'o dia todo',
            untitled: 'Compromisso',
            none: 'nada à vista',
            reconnect: 'reconectar',
            unavailable: 'indisponível',
            weekdays: ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'],
        },
        weather: {
            0: 'Céu limpo',
            1: 'Predominantemente limpo',
            2: 'Parcialmente nublado',
            3: 'Encoberto',
            45: 'Neblina',
            48: 'Neblina congelante',
            51: 'Garoa fraca',
            53: 'Garoa',
            55: 'Garoa forte',
            61: 'Chuva fraca',
            63: 'Chuva',
            65: 'Chuva forte',
            71: 'Neve fraca',
            73: 'Neve',
            75: 'Neve forte',
            80: 'Pancadas fracas',
            81: 'Pancadas',
            82: 'Pancadas violentas',
            95: 'Trovoada',
            96: 'Trovoada com granizo',
            99: 'Trovoada com granizo forte',
        },
    },
    en: {
        tag: 'en',
        unknown: 'Unknown',
        rainChance: 'Chance of rain',
        moon: {
            'new': 'New moon',
            'waxing-crescent': 'Waxing crescent',
            'first-quarter': 'First quarter',
            'waxing-gibbous': 'Waxing gibbous',
            'full': 'Full moon',
            'waning-gibbous': 'Waning gibbous',
            'last-quarter': 'Last quarter',
            'waning-crescent': 'Waning crescent',
        },
        stale: 'STALE',
        marketClosed: 'CLOSED',
        unplugged: 'unplugged',
        // SCHEDULE, not AGENDA: in English an agenda is the list of items
        // for one meeting, and what this card will show is the next one.
        titles: { quotes: 'B3', fx: 'FX', crypto: 'CRYPTO', weather: 'WEATHER',
                  agenda: 'SCHEDULE' },
        actions: { 'mute-audio': 'SOUND', 'mute-mic': 'MIC' },
        actionHint: 'Toggle mute',
        actionFailed: 'failed',
        actionMuted: 'muted when last asked',
        actionUnmuted: 'not muted when last asked',
        agenda: {
            in: 'in',
            now: 'now',
            until: 'until',
            today: 'today',
            tomorrow: 'tomorrow',
            allDay: 'all day',
            untitled: 'Meeting',
            none: 'nothing ahead',
            reconnect: 'reconnect',
            unavailable: 'unavailable',
            weekdays: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
        },
        weather: {
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
        },
    },
};

// The panel's language when the config says nothing, which is where it stands.
const FALLBACK_LANGUAGE = 'pt-BR';

// The vocabulary for one language tag, never null.
//
// The fallback is the panel's own language and not English, and it is the same
// decision `host.useTheme` makes about an unknown theme name: a typo in a file
// on the PC costs nothing anybody can see, rather than turning the whole panel
// into a language its owner did not ask for. Matched on the tag's primary
// subtag as well, so "pt", "pt-PT" and "en-GB" all land somewhere sensible --
// a config that says "pt" is not wrong enough to ignore.
function strings(language) {
    if (typeof language !== 'string' || !language) {
        return LANGUAGES[FALLBACK_LANGUAGE];
    }
    if (LANGUAGES[language]) {
        return LANGUAGES[language];
    }
    const primary = language.split('-')[0].toLowerCase();
    for (const tag of Object.keys(LANGUAGES)) {
        if (tag.split('-')[0].toLowerCase() === primary) {
            return LANGUAGES[tag];
        }
    }
    return LANGUAGES[FALLBACK_LANGUAGE];
}

/**
 * The shortcut buttons a theme should draw, in the order the PC sent them.
 *
 * Pure, and the rule it encodes is T8.2 step 5's: **a theme renders nothing
 * for an action it does not recognise**, rather than a button that cannot
 * work. An id the server enabled but this build has no word for is a button
 * whose caption would be the raw id -- `mute-everything` under the clock --
 * and a button nobody can read is worse than a gap where one would be.
 *
 * That is also what makes a third action a config change and not a rebuild in
 * only one direction: the PC can *remove* a button by editing a file, and can
 * add one only for an id the APK already has words for. The asymmetry is
 * deliberate and is the same shape as the server's own catalogue (ADR 0015).
 *
 * @param actions  the payload's `actions`: ids the server says it will accept
 * @param language the payload's `language`
 * @returns [{id, label, hint}], possibly empty, never null
 */
function shortcutsFor(actions, language) {
    if (!Array.isArray(actions)) {
        return [];
    }
    const words = strings(language);
    const seen = {};
    const out = [];
    for (const id of actions) {
        if (typeof id !== 'string' || seen[id] || !words.actions[id]) {
            continue;
        }
        seen[id] = true;
        out.push({ id: id, label: words.actions[id], hint: words.actionHint });
    }
    return out;
}

// --- The next meeting (T9.1, ADR 0017) --------------------------------------
//
// The PC sends up to five events -- three timed, two all-day -- as absolute
// instants and nothing else: it
// has already dropped the declined and the cancelled, and it never sends a
// countdown. Which event is next, and how long until it starts, is decided
// here against **the phone's clock**, exactly as isNight is -- the panel is
// what sits on the desk, and a payload is up to a minute old by the time it
// is drawn. A server that said "in 25 min" would be wrong by the age of the
// payload, every time.

// "YYYY-MM-DD", which is what the server sends for an all-day event. Parsed
// into *local* midnight by hand: `new Date('2026-09-30')` is UTC midnight by
// the spec, which in Brazil is 21:00 the day before, and the all-day event
// would start the evening before it.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
// An RFC 3339 instant with its offset. The offset is required: an instant
// without one would be read in the phone's zone, which is a guess.
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

function parseLocalDate(text) {
    const match = typeof text === 'string' ? DATE_ONLY.exec(text) : null;
    if (!match) {
        return null;
    }
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    // Rejects 2026-02-31, which Date would silently roll into March.
    return date.getMonth() === Number(match[2]) - 1 ? date : null;
}

function parseInstant(text) {
    if (typeof text !== 'string' || !INSTANT.test(text)) {
        return null;
    }
    const ms = Date.parse(text);
    return Number.isNaN(ms) ? null : new Date(ms);
}

// Days since the epoch *on the local calendar*. The difference of two of these
// is how many midnights lie between two moments, which is what "tomorrow"
// means. Dividing a millisecond difference by 86,400,000 is not: across a DST
// change a day is 23 or 25 hours, and 23:30 to 00:30 is one day apart in an
// hour.
function localDay(date) {
    return Math.round(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000);
}

// "Within the hour": the window in which a meeting tomorrow counts as today's
// for nextEvent -- the same hour in which untilText says minutes rather than
// a day, so the card cannot put an all-day event above a meeting it would
// have called "in 20 min".
const SOON_MS = 60 * 60000;

function hhmm(date) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

// One event from the payload, or null for anything that is not one. The
// payload is data from a file on another machine; a malformed row costs itself
// and nothing else, the same bargain every list on this panel makes.
function normaliseEvent(raw) {
    if (!raw || typeof raw !== 'object') {
        return null;
    }
    const source = typeof raw.source === 'string' ? raw.source : '';
    const title = typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : null;
    if (raw.allDay === true) {
        const start = parseLocalDate(raw.start);
        if (!start) {
            return null;
        }
        const parsedEnd = parseLocalDate(raw.end);
        // `end` is exclusive, as both providers send it. A missing or
        // backwards one means a single day.
        const end = parsedEnd && parsedEnd > start
            ? parsedEnd
            : new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1);
        return { event: raw, start, end, allDay: true, source, title };
    }
    const start = parseInstant(raw.start);
    if (!start) {
        return null;
    }
    const parsedEnd = parseInstant(raw.end);
    const end = parsedEnd && parsedEnd >= start ? parsedEnd : start;
    return { event: raw, start, end, allDay: false, source, title };
}

/**
 * The one event the card should show, or null.
 *
 * The order is what a person at the desk wants to know first:
 *
 *   1. a timed event **in progress** -- the meeting you are late for is more
 *      urgent than the one after it, and skipping to the next would hide it.
 *      Of several in progress, the one that started **last** wins: a 09-18
 *      focus block must not hide the 14:00 meeting that has just begun inside
 *      it, which is exactly the meeting you are late for;
 *   2. a timed event still to start **today**, or starting within the hour
 *      whatever day that is -- at 23:50 a meeting at 00:10 is "in 20 min" and
 *      it outranks the all-day event that ends at midnight, which is what
 *      untilText promises about the same case;
 *   3. an all-day event covering today -- it has no time, so it is not a
 *      countdown, and a real meeting at 15:00 is the more useful line;
 *   4. anything later, by day, with a timed event before an all-day one on
 *      the same day.
 *
 * Inside a tier after the first, earliest start wins; ties break on (source,
 * title) everywhere, so two
 * meetings in the same minute always come out in the same order. Without it
 * the card would flip between them on every payload, for ever.
 *
 * A timed event that has ended is gone. An event exactly at its end instant
 * has ended: `end` is exclusive, as it is in both providers.
 *
 * @param events the payload's `agenda.events`
 * @param now    Date, the phone's clock
 * @returns {event, start, end, allDay, inProgress, source, title} or null
 */
function nextEvent(events, now) {
    const ranked = rankedEvents(events, now);
    return ranked.length ? ranked[0] : null;
}

// Every event still on the card, best first, by nextEvent's order. The same
// ranking for the first row and the second, so the card never shows as
// "next" something nextEvent would have put behind it.
function rankedEvents(events, now) {
    if (!Array.isArray(events) || !(now instanceof Date) || Number.isNaN(now.getTime())) {
        return [];
    }
    const today = localDay(now);
    const ranked = [];
    for (const raw of events) {
        const item = normaliseEvent(raw);
        if (!item) {
            continue;
        }
        let tier;
        let inProgress = false;
        if (item.allDay) {
            if (localDay(item.end) <= today) {
                continue;
            }
            tier = localDay(item.start) <= today ? 3 : 4;
        } else if (item.start > now) {
            tier = localDay(item.start) === today || item.start - now < SOON_MS ? 2 : 4;
        } else if (now < item.end) {
            tier = 1;
            inProgress = true;
        } else {
            // Ended -- and a zero-length event, a reminder, ends the moment
            // it starts.
            continue;
        }
        ranked.push(Object.assign({}, item, { tier, inProgress }));
    }
    ranked.sort((a, b) => (
        a.tier - b.tier
        || (a.tier === 1 ? b.start - a.start : 0)
        || localDay(a.start) - localDay(b.start)
        || (a.allDay === b.allDay ? 0 : (a.allDay ? 1 : -1))
        || a.start - b.start
        || (a.source < b.source ? -1 : a.source > b.source ? 1 : 0)
        || ((a.title || '') < (b.title || '') ? -1 : (a.title || '') > (b.title || '') ? 1 : 0)
    ));
    for (const item of ranked) {
        delete item.tier;
    }
    return ranked;
}

/**
 * How long until `start`, as the card says it: `em 3 min`, `em 1 h 10`,
 * `agora`, `amanhã 09:00`, `qua 09:00`.
 *
 * Minutes round **up**, so the line never says "in 0 min" about a meeting that
 * has not started, and at 13:57:30 a 14:00 meeting is "in 3 min" -- the number
 * that gets you there on time. Under an hour is always minutes, even across
 * midnight: at 23:50 a meeting at 00:10 is "in 20 min", not "tomorrow 00:10".
 * A start that has passed is "now"; the caller only asks about an event that
 * is still on the card, so a past start means it is in progress.
 *
 * @param start    Date
 * @param now      Date, the phone's clock
 * @param language the payload's `language`
 */
function untilText(start, now, language) {
    const w = strings(language).agenda;
    if (!(start instanceof Date) || Number.isNaN(start.getTime())
        || !(now instanceof Date) || Number.isNaN(now.getTime())) {
        return '';
    }
    const ms = start - now;
    if (ms <= 0) {
        return w.now;
    }
    const minutes = Math.ceil(ms / 60000);
    if (minutes < 60) {
        return `${w.in} ${minutes} min`;
    }
    const days = localDay(start) - localDay(now);
    if (days === 0) {
        const h = Math.floor(minutes / 60);
        const m = minutes % 60;
        return m ? `${w.in} ${h} h ${String(m).padStart(2, '0')}` : `${w.in} ${h} h`;
    }
    return `${dayWord(start, days, w)} ${hhmm(start)}`;
}

// "amanhã", or the weekday for the rest of the week, or the weekday with the
// day of the month beyond it -- a lookahead longer than a week is a config
// choice, and "qua" alone would then be ambiguous.
function dayWord(date, days, w) {
    if (days === 1) {
        return w.tomorrow;
    }
    const weekday = w.weekdays[date.getDay()];
    return days < 7 ? weekday : `${weekday} ${String(date.getDate()).padStart(2, '0')}`;
}

// The failed accounts as one line, grouped by what the owner has to do:
// "google/personal: reconectar · microsoft/work: indisponível". `reconnect`
// means the login was refused or never run, and only the owner can fix it on
// the PC; `unavailable` means the provider or the network is down and the
// server retries by itself. A bare string is read as `reconnect`, the answer
// that asks for action, because an entry this build cannot read is safer
// treated as one somebody has to look at.
function failedLine(failed, w) {
    if (!Array.isArray(failed)) {
        return null;
    }
    const groups = { reconnect: [], unavailable: [] };
    for (const entry of failed) {
        if (typeof entry === 'string' && entry) {
            groups.reconnect.push(entry);
        } else if (entry && typeof entry === 'object' && typeof entry.source === 'string' && entry.source) {
            groups[entry.reason === 'unavailable' ? 'unavailable' : 'reconnect'].push(entry.source);
        }
    }
    const parts = [];
    for (const reason of ['reconnect', 'unavailable']) {
        if (groups[reason].length) {
            parts.push(`${groups[reason].join(', ')}: ${w[reason]}`);
        }
    }
    return parts.length ? parts.join(' · ') : null;
}

/**
 * Everything a theme needs to draw the AGENDA card, as strings, or null when
 * there is no card to draw: an older server (no `agenda`) or a PC with no
 * calendar connected (`accounts` 0). Both leave the card reserved, as it was
 * before T9.1.
 *
 *   title      the event's title, the generic word when titles are off on the
 *              PC, or null when there is no event at all
 *   when       the countdown, "agora · até 14:30" in progress, "o dia todo"
 *              for an all-day event today, or "nada à vista"
 *   until      "até 14:30" while the event is running, else null: the half
 *              of `when` a theme that says "in progress" some other way --
 *              neon does it in colour -- can draw on its own. At neon's
 *              countdown size the whole of `when` does not fit the card
 *   inProgress true while the event is running, for a theme that marks it
 *   failed     "google/personal: reconectar", "microsoft/work: indisponível",
 *              or null (see failedLine). With no event and a failure, `when`
 *              is empty rather than "nada à vista". A failed account is
 *              named and the rest of the card still draws: the other
 *              provider's meeting is still the next meeting.
 *
 * @param agenda   the payload's `agenda`
 * @param now      Date, the phone's clock
 * @param language the payload's `language`
 */
function agendaFields(agenda, now, language) {
    if (!agenda || typeof agenda !== 'object' || !(Number(agenda.accounts) > 0)) {
        return null;
    }
    const w = strings(language).agenda;
    const failed = failedLine(agenda.failed, w);
    const next = nextEvent(agenda.events, now);
    if (!next) {
        // "Nothing ahead" is a claim, and with an account failing the panel
        // cannot make it: the meeting may be in the calendar it could not
        // read. The failure line is the whole card then.
        return { title: null, when: failed ? '' : w.none, until: null, inProgress: false, failed };
    }
    let when;
    let until = null;
    if (next.allDay) {
        const days = localDay(next.start) - localDay(now);
        when = days <= 0 ? w.allDay : dayWord(next.start, days, w);
    } else if (next.inProgress) {
        // With the day when it ends on another one: "até 10:00" about a
        // conference that ends on Thursday reads as this morning, already past.
        const endDays = localDay(next.end) - localDay(now);
        const endText = endDays === 0 ? hhmm(next.end) : `${dayWord(next.end, endDays, w)} ${hhmm(next.end)}`;
        until = next.end > next.start ? `${w.until} ${endText}` : null;
        when = until ? `${w.now} · ${until}` : w.now;
    } else {
        when = untilText(next.start, now, language);
    }
    return { title: next.title || w.untitled, when, until, inProgress: next.inProgress, failed };
}

// How long is left of a meeting in progress, as the right-hand end of its
// row: "58 min", "1 h 10". Rounded up like untilText, so a meeting with 30
// seconds left says "1 min" and not "0 min" -- the caller only asks while
// `end` is still ahead, so the ceiling is never below one.
function remainingText(end, now) {
    const minutes = Math.ceil((end - now) / 60000);
    if (minutes < 60) {
        return `${minutes} min`;
    }
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`;
}

// "até 14:30", or with the day when it ends on another one.
function untilEnd(event, now, w) {
    const endDays = localDay(event.end) - localDay(now);
    const endText = endDays === 0 ? hhmm(event.end) : `${dayWord(event.end, endDays, w)} ${hhmm(event.end)}`;
    return `${w.until} ${endText}`;
}

function agendaRow(event, now, language, primary) {
    const w = strings(language).agenda;
    const row = {
        title: event.title || w.untitled,
        icon: 'clock',
        live: false,
        when: '',
        aside: null,
        progress: null,
    };
    if (event.allDay) {
        const days = localDay(event.start) - localDay(now);
        row.icon = 'calendar';
        row.when = days <= 0 ? w.allDay : dayWord(event.start, days, w);
    } else if (event.inProgress) {
        row.icon = 'live';
        row.live = true;
        row.when = untilEnd(event, now, w);
        // Only when it ends today. "até amanhã 10:00" is the whole line at
        // this size, and "20 h 25" beside it cut off the time the row is for.
        const endsToday = localDay(event.end) === localDay(now);
        row.aside = endsToday ? remainingText(event.end, now) : null;
        // In [0, 1) by construction: rankedEvents only marks an event in
        // progress while start <= now < end, which also makes the span > 0.
        row.progress = (now - event.start) / (event.end - event.start);
    } else {
        const minutes = Math.ceil((event.start - now) / 60000);
        const today = localDay(event.start) === localDay(now);
        if (!primary && today && minutes >= 60) {
            // A later row says a clock time rather than a long countdown:
            // "14:30" says what "em 3 h 10" does, in fewer characters, and
            // the same on every row after the first however the theme lays
            // them out.
            row.when = hhmm(event.start);
        } else {
            row.when = untilText(event.start, now, language);
        }
        // On the first row, the clock time beside a countdown for whoever
        // wants to know when that is: "em 25 min" today, and "em 20 min" at
        // 23:50 about a meeting at 00:10 as well. "amanhã 09:00" already
        // says its time, and saying it twice is noise.
        if (primary && (today || minutes < 60)) {
            row.aside = hhmm(event.start);
        }
    }
    return row;
}

// The most rows agendaRows returns; how many of them to draw is the theme's.
const AGENDA_MAX_ROWS = 3;

/**
 * The AGENDA card as rows, for a theme that shows more than the next event:
 * up to three, best first by nextEvent's ranking, or null when there is no card
 * to draw (the same two cases as agendaFields).
 *
 *   rows     [{ title, icon, live, when, aside, progress }], at most three:
 *              icon      'live' (in progress), 'clock' (timed), 'calendar'
 *                        (all day) -- a name, never markup
 *              when      "até 23:30" in progress, "em 25 min", "amanhã
 *                        09:00", "o dia todo"; on any row after the first
 *                        a timed event today and an hour or more away is
 *                        "14:30"
 *              aside     the right-hand end of the row: what is left of a
 *                        meeting in progress that ends today ("58 min"), or
 *                        the start time beside a countdown on the first row,
 *                        or null
 *              progress  0..1 through a meeting in progress, else null
 *   none     "nada à vista" when there is nothing and no failure, else null
 *   failed   as agendaFields
 *
 * @param agenda   the payload's `agenda`
 * @param now      Date, the phone's clock
 * @param language the payload's `language`
 */
function agendaRows(agenda, now, language) {
    if (!agenda || typeof agenda !== 'object' || !(Number(agenda.accounts) > 0)) {
        return null;
    }
    const w = strings(language).agenda;
    const failed = failedLine(agenda.failed, w);
    // Up to three, and how many of them fit is the theme's call: neon draws
    // three, or two when a failure line needs the room.
    const events = rankedEvents(agenda.events, now).slice(0, AGENDA_MAX_ROWS);
    return {
        rows: events.map((event, i) => agendaRow(event, now, language, i === 0)),
        none: events.length || failed ? null : w.none,
        failed,
    };
}

// How many of a progress bar's `segments` are lit for `progress` in [0, 1],
// or null. Floor, not round: a full bar means the meeting is over, and with
// round a 60-minute meeting read 10 of 10 from its 57th minute.
function agendaSegments(progress, segments) {
    if (typeof progress !== 'number' || !Number.isFinite(progress)) {
        return 0;
    }
    return Math.min(segments, Math.max(0, Math.floor(progress * segments)));
}

function weatherLabel(code, language) {
    const table = strings(language);
    return table.weather[code] || table.unknown;
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

// The two codes that are about the *sky* rather than about weather, and so the
// only two that look different after dark. Rain at night is still rain; a clear
// sky at night is not a sun, which is the complaint this came from -- the panel
// drew a sun for `Predominantemente limpo` at 21:20 with the window dark.
//
// `clear` at night is stars and not a moon, deliberately. The moon has its own
// permanent place on the card now, beside the temperature, with its phase and
// how much of it is lit; drawing it twice would be the card telling you the
// same thing in two sizes.
const NIGHT_GLYPHS = {
    clear: 'stars',
    cloudy: 'cloudy-night',
};

// isDay defaults to true, so every existing caller keeps its meaning and a
// server too old to send the field behaves exactly as it did. Absent means day
// in the server's normalise too, and for the same reason: a panel drawing a sun
// at midnight was the bug, and one drawing a moon at noon would be stranger.
function weatherGlyph(code, isDay) {
    const glyph = WEATHER_GLYPHS[code] || 'unknown';
    if (isDay === false && NIGHT_GLYPHS[glyph]) {
        return NIGHT_GLYPHS[glyph];
    }
    return glyph;
}

// The eight phase names, in the order a lunation visits them. The same list and
// the same order as `server/providers_usno.PHASE_NAMES`, and a test asserts the
// two agree: the server decides which name it is and this file decides what the
// name is called, so a table that drifted would draw a waxing crescent and call
// it waning.
const MOON_PHASES = [
    'new',
    'waxing-crescent',
    'first-quarter',
    'waxing-gibbous',
    'full',
    'waning-gibbous',
    'last-quarter',
    'waning-crescent',
];

// Which limb is lit, and it is **not** read off the phase name.
//
// The first cut was `index >= 1 && index <= 3`, and the review caught what that
// does around the two phases that are a name rather than a side. The buckets
// are an eighth of a lunation wide, so `full` covers about 1.85 days either
// side of the instant and arrives with `illum` as low as 96%. For the half of
// that bucket the moon is still waxing, the name-based test said waning, the
// lit limb flipped, and the four-percent dark sliver was drawn on the wrong
// edge -- the one error on this card a reader can catch by looking up, which is
// the entire reason the phase is drawn rather than written.
//
// The age is what actually knows: the first half of a lunation is growing and
// the second is shrinking. `ageDays` and `lunationDays` both come from the
// server (real values from the USNO's table, or the mean model's), so this is a
// division rather than a guess.
//
// The name is the fallback for a server too old to send them, where being right
// three-quarters of the month is better than not drawing a moon.
function isWaxing(moon, index) {
    const age = moon.ageDays;
    const lunation = moon.lunationDays;
    if (Number.isFinite(age) && Number.isFinite(lunation) && lunation > 0) {
        return ((age / lunation) % 1.0) < 0.5;
    }
    return index >= 1 && index <= 3;
}

// moon: the payload's `weather.moon`, or undefined before the first broadcast
// and on a server too old to send it. Returns `{phase, illum, waxing, label}`
// or null when there is nothing worth drawing.
//
// `waxing` is derived rather than carried because it is a property of the name:
// the first half of the cycle is growing and the second is shrinking, and the
// theme needs it to decide which limb of the moon is lit. The southern
// hemisphere sees the terminator on the opposite side from the northern one --
// this panel is in Sao Paulo and draws the southern convention, which is a
// known simplification for a panel that travels (docs/THEMING.md).
function moonFields(moon, words) {
    if (!moon || typeof moon !== 'object') {
        return null;
    }
    const index = MOON_PHASES.indexOf(moon.phase);
    if (index < 0) {
        return null;
    }
    const illum = Number.isFinite(moon.illum)
        ? Math.max(0, Math.min(100, Math.round(moon.illum))) : null;
    const table = (words && words.moon) || {};
    return {
        phase: moon.phase,
        illum: illum,
        waxing: isWaxing(moon, index),
        label: table[moon.phase] || moon.phase,
    };
}

// weather.precipProb -> a whole percentage in [0, 100], or null.
//
// Clamped rather than trusted: the field comes from a provider and a panel that
// drew `140%` would be wrong in the one way nobody would report, because it
// looks like a bug in the number rather than in the panel.
//
// There is no wording anywhere near this. Asked for from the chair as "sem
// palavra, com icone de chuva": a drop and a number, and the card stays
// readable in a language nobody has translated it into.
function chanceOfRain(weather) {
    const value = weather && weather.precipProb;
    if (!Number.isFinite(value)) {
        return null;
    }
    return Math.max(0, Math.min(100, Math.round(value)));
}

// A whole percentage, or null. Two callers and the same rule for both: the lit
// fraction of the moon, and the day's chance of rain.
//
// One function rather than two identically-shaped ones, which is what the first
// cut had. The semantics differ and the formatting does not, and a second copy
// is a second place for the `--%` decision to be made differently.
//
// Never `--%`. That pattern is right for a temperature, where the number *is*
// the statement and a missing one has to be visible as missing; here the icon
// beside it carries the meaning on its own -- a moon with no number is still a
// moon at a phase, and a rain drop with no number is still "rain is the thing
// this card has an opinion about". null asks the theme to draw the icon alone.
function formatPercent(value) {
    return Number.isFinite(value) ? `${Math.round(value)}%` : null;
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
// first broadcast. Returns the whole device line, or '' when there is nothing
// worth saying -- app.js renders nothing at all for '', rather than an empty
// box with a label in it.
//
// "BAT" rather than a card title: T5.4 demotes this from a card to a line, so
// the line has to say what it is on its own. Three characters is the cheapest
// way to do that.
// The battery line taken apart, so a theme can decide what to draw beside each
// piece (T6.10). null when there is nothing worth a corner at all.
//
// Split out of formatBattery, which now composes its string from this, so the
// two can never disagree about what the line says. The reason a theme needs
// the pieces is that `neon` draws an icon in front of two of them and a bare
// string cannot be taken apart afterwards -- not reliably, and not at all once
// the separator is a character somebody's locale also uses.
//
//   level      "87%", always present
//   temp       "31°C", or null when the phone sent no usable temperature
//   unplugged  true only when the phone said so
function batteryFields(battery) {
    if (!battery || typeof battery.level !== 'number' || !Number.isFinite(battery.level)) {
        return null;
    }
    // Reuses formatTemp, so an absent temperature is drawn as an absence here
    // exactly as it is in the weather line. The native side leaves the key out
    // rather than sending a zero, for the same reason the server does.
    const temp = formatTemp(battery.tempC);
    return {
        level: `${Math.round(battery.level)}%`,
        temp: temp === '--' ? null : `${temp}°C`,
        // Only the interesting half is worth saying. On this desk the phone is
        // powered from the PC's USB, so charging is the resting state and
        // saying so every second of every day would spend the line's width on
        // no information; unplugged is the condition worth a word, because it
        // means the panel is now running the battery down (ADR 0014).
        //
        // `=== false` and not `!charging`: a payload with no `charging` key at
        // all has not said the phone is on battery, and the corner must not
        // claim it has.
        unplugged: battery.charging === false,
    };
}

// The whole line as one string, for a theme that draws no icons. `BAT` stays
// English-shaped because it is the same abbreviation in both languages the
// panel ships; the one real word in the line comes from the table.
function formatBattery(battery, language) {
    const fields = batteryFields(battery);
    if (!fields) {
        return '';
    }
    const parts = [`BAT ${fields.level}`];
    if (fields.temp) {
        parts.push(fields.temp);
    }
    if (fields.unplugged) {
        parts.push(strings(language).unplugged);
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
// One minute, and the reason is the table below rather than the clock. Four
// minutes was chosen when a step was up to four pixels and the argument was
// that you would not catch it every time you looked up. **You do**: it was
// reported from the chair as "uma pulada", and measured on the device -- the
// whole panel moving (-8, +2) physical pixels between one screenshot and the
// next, instantaneously, with the eye pointed straight at it. A step that is
// one pixel does not need to be rare, so it can be frequent instead, and the
// ink now moves sixty times an hour rather than fifteen.
const BURN_IN_STEP_MINUTES = 1;

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
// Twenty-two steps over twenty positions, and **every step moves exactly one
// pixel -- the one that wraps back to the start included.** That is the whole
// design, and it replaces a seven-position table whose steps were up to four.
//
// The old ordering was deliberate and its stated reason was that "a slow raster
// leaves each position adjacent to the last, which is the least relief per
// move". True of one move, and the wrong quantity: what spares an AMOLED is how
// long any single pixel stays lit across hours, which is coverage over time,
// and coverage here is better -- twenty positions of the band in twenty-two
// minutes against seven in twenty-eight. What the big steps bought was a
// visible jolt four times an hour. It was reported from the chair as "uma
// pulada" and then measured on the device: the whole panel moving (-8, +2)
// physical pixels between one screenshot and the next, instantaneous, with the
// eye pointed straight at it. Changed from the chair with the trade-off put in
// those terms.
//
// Three things about the shape of the table are arithmetic rather than taste,
// and each one cost an attempt:
//
//   - **The band is 5 wide by 4 tall, not 5 by 5.** A grid graph is bipartite,
//     a 5x5 grid splits 13 / 12, and a closed tour of an odd number of its
//     nodes cannot exist -- so the wrap from the last position to the first
//     would have been a three-pixel jump: the exact thing being removed. An
//     even side makes the tour closeable. The cost is one pixel of vertical
//     relief, which still clears an antialiased edge of one or two pixels.
//   - **Twenty-two steps, not twenty.** A closed tour of the 5x4 band is twenty
//     positions long, and at a minute each that is a twenty-minute cycle --
//     which divides 1440, so the panel would stand at the same offset at the
//     same time every day and etch the same pattern night after night. That is
//     the property `offsetFor does not put the panel in the same place at the
//     same time tomorrow` has always asserted, and twenty would have broken it
//     silently. 1440 % 22 is 10, so the phase walks.
//   - **The two extra steps are a one-pixel detour**, not a jump: the tour
//     bounces between (-4, 0) and (-3, 0) once. Those two positions are
//     therefore held twice per cycle and the other eighteen once.
//
// Four properties, all asserted in web/test/format.test.js rather than claimed
// here -- an earlier version of this comment promised something seven entries
// could not have, which is what earned the tests:
//
//   - consecutive positions differ by exactly one pixel, the wrap included,
//   - all twenty positions of the 5x4 band appear,
//   - the cycle length does not divide a day,
//   - each axis's mean is within a fifth of a pixel of the middle of its band
//     (-2 in x, -1.5 in y), so the panel has no standing offset worth the name.
//     Not exactly the midpoint: the detour above visits two positions twice,
//     and a table that hit the midpoints exactly needed a cycle of 26 whose
//     dwell was three times longer on some positions than others. An eighth of
//     a pixel of bias is cheaper than that.
const BURN_IN_OFFSETS = [
    { x: 0, y: 0 },
    { x: -1, y: 0 },
    { x: -2, y: 0 },
    { x: -3, y: 0 },
    { x: -4, y: 0 },
    { x: -3, y: 0 },
    { x: -4, y: 0 },
    { x: -4, y: -1 },
    { x: -3, y: -1 },
    { x: -2, y: -1 },
    { x: -1, y: -1 },
    { x: -1, y: -2 },
    { x: -2, y: -2 },
    { x: -3, y: -2 },
    { x: -4, y: -2 },
    { x: -4, y: -3 },
    { x: -3, y: -3 },
    { x: -2, y: -3 },
    { x: -1, y: -3 },
    { x: 0, y: -3 },
    { x: 0, y: -2 },
    { x: 0, y: -1 },
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
    // whole reason this is not a rota. A day is 1440 one-minute steps against a
    // cycle of twenty-two, and 1440 mod 22 is 10, so the phase advances ten
    // steps a night and the cycle index is somewhere new for eleven days before
    // it comes back round.
    //
    // The *index*, not the offset. Two positions in the table are visited
    // twice -- the one-pixel detour above -- so for four of the twenty-two
    // phases the offset after two days is genuinely the same one. The review
    // caught that: the test asserting otherwise passed in America/Sao_Paulo
    // and failed in Europe/Lisbon, because which index a fixed local hour
    // lands on depends on the machine's timezone.
    //
    // Counting from midnight was the first cut and it fails the thing the
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
// means the worst case is measured one run in twenty-two and a layout that only
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

// Whether to draw the CLOSED label beside the B3 title. The server decides
// whether the exchange is open (server/market_hours.py -- the window follows
// US daylight saving, which the page has no business knowing); this only
// reads its answer, and only an explicit `false` counts. An older server
// sends no `b3Open` at all, and a panel that called that "closed" would say
// so all day.
function marketClosed(payload) {
    return !!payload && payload.b3Open === false;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        formatPrice, formatRate, formatPair, formatTemp, formatChange, changeClass,
        weatherLabel, weatherGlyph, formatRange,
        moonFields, formatPercent, chanceOfRain, MOON_PHASES,
        strings, LANGUAGES, FALLBACK_LANGUAGE,
        isNight,
        offsetFor, burnInSchedule,
        BURN_IN_OFFSETS, BURN_IN_STEP_MINUTES, BURN_IN_AMPLITUDE_PX,
        overflowsBy, scrollPlan, worthScrolling,
        SCROLL_SECONDS_PER_ROW, SCROLL_MIN_TRAVEL_PX, SCROLL_MIN_HIDDEN_ROWS,
        sparklinePath,
        formatBattery, batteryFields, tempClass, BATTERY_WARN_C, BATTERY_HOT_C,
        shortcutsFor,
        nextEvent, untilText, agendaFields, agendaRows, agendaSegments,
        marketClosed,
    };
}
