'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    formatPrice, formatRate, formatPair, formatChange, changeClass, weatherLabel, isNight,
    sparklinePath, formatTemp, formatBattery, batteryFields, tempClass,
    BATTERY_WARN_C, BATTERY_HOT_C,
    formatRange, weatherGlyph, strings, LANGUAGES, FALLBACK_LANGUAGE,
    moonFields, formatPercent, chanceOfRain, MOON_PHASES,
    overflowsBy, scrollPlan, worthScrolling,
    SCROLL_SECONDS_PER_ROW, SCROLL_MIN_TRAVEL_PX, SCROLL_MIN_HIDDEN_ROWS,
    offsetFor, burnInSchedule,
    BURN_IN_OFFSETS, BURN_IN_STEP_MINUTES, BURN_IN_AMPLITUDE_PX,
    shortcutsFor, marketClosed,
} = require('../js/format.js');

test('formatPrice formats a BRL price with two decimals', () => {
    assert.equal(formatPrice(38.42, 'BRL'), 'R$38.42');
});

test('formatPrice formats a six-figure crypto price with thousand separators', () => {
    assert.equal(formatPrice(234567.891, 'USD'), '$234,567.89');
});

test('formatPrice returns a placeholder for non-numeric input', () => {
    assert.equal(formatPrice(NaN, 'USD'), '--');
    assert.equal(formatPrice(undefined, 'USD'), '--');
});

test('formatChange formats a positive change with a leading sign', () => {
    assert.equal(formatChange(1.234), '+1.2%');
});

test('formatChange formats a negative change with a leading sign', () => {
    assert.equal(formatChange(-0.87), '-0.9%');
});

test('formatChange formats zero change without a sign', () => {
    assert.equal(formatChange(0), '0.0%');
});

test('changeClass buckets positive, negative and zero', () => {
    assert.equal(changeClass(2.5), 'up');
    assert.equal(changeClass(-2.5), 'down');
    assert.equal(changeClass(0), 'flat');
});

test('weatherLabel maps a known WMO code, in the panel\'s own language', () => {
    assert.equal(weatherLabel(95), 'Trovoada');
    assert.equal(weatherLabel(95, 'en'), 'Thunderstorm');
});

test('weatherLabel falls back to a named condition for an unmapped code', () => {
    assert.equal(weatherLabel(9999), 'Desconhecido');
    assert.equal(weatherLabel(9999, 'en'), 'Unknown');
});

// --- T6.11: every word the panel shows -------------------------------------

test('the panel speaks pt-BR unless the PC says otherwise', () => {
    // The default is where the panel stands, not the language this repository
    // is written in. Everything else here -- code, comments, docs, commits --
    // is English; what a person reads from a chair is not code.
    assert.equal(FALLBACK_LANGUAGE, 'pt-BR');
    assert.equal(strings(undefined), LANGUAGES['pt-BR']);
    assert.equal(strings(''), LANGUAGES['pt-BR']);
});

test('an unknown language falls back to the panel\'s own, not to English', () => {
    // The same decision host.useTheme makes about an unknown theme name: a
    // typo in a file on the PC must cost nothing anybody can see, rather than
    // turning the whole panel into a language its owner did not ask for.
    assert.equal(strings('klingon'), LANGUAGES['pt-BR']);
    assert.equal(strings(42), LANGUAGES['pt-BR']);
    assert.equal(strings(null), LANGUAGES['pt-BR']);
});

test('a bare or regional tag lands on the language it names', () => {
    // A config that says "pt" is not wrong enough to ignore, and neither is
    // one that says "en-GB" on a panel that only ships "en".
    assert.equal(strings('pt'), LANGUAGES['pt-BR']);
    assert.equal(strings('pt-PT'), LANGUAGES['pt-BR']);
    assert.equal(strings('en-GB'), LANGUAGES.en);
    assert.equal(strings('EN'), LANGUAGES.en);
});

test('each table answers to the tag it is filed under', () => {
    // `words.tag` is what reaches Intl for the date, so a table filed under
    // one tag and carrying another would render the panel's words in one
    // language and its date in the other -- which is exactly the split T6.11
    // exists to close.
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        assert.equal(table.tag, tag);
    }
});

test('every language says every word the panel needs', () => {
    // The whole reason the strings are tables and not scattered lookups: a
    // missing key would render as `undefined` in a corner of somebody's
    // panel, and nothing else in this repo would notice. Compared against the
    // fallback rather than against a hand-written list, so adding a word to
    // the panel adds it to this check for free.
    const reference = LANGUAGES[FALLBACK_LANGUAGE];
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        assert.deepEqual(Object.keys(table).sort(), Object.keys(reference).sort(),
                         `${tag} does not have the same keys as ${FALLBACK_LANGUAGE}`);
        assert.deepEqual(Object.keys(table.weather).sort(),
                         Object.keys(reference.weather).sort(),
                         `${tag} does not name every WMO code`);
        assert.deepEqual(Object.keys(table.titles).sort(),
                         Object.keys(reference.titles).sort(),
                         `${tag} does not name every card`);
        for (const [key, value] of Object.entries(table)) {
            if (typeof value === 'string') {
                assert.ok(value.length > 0, `${tag}.${key} is empty`);
            }
        }
        for (const [code, value] of Object.entries(table.weather)) {
            assert.ok(value && value.length > 0, `${tag}.weather.${code} is empty`);
        }
    }
});

test('isNight is true well inside a night window that does not wrap midnight', () => {
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), 22, 23), false);
    assert.equal(isNight(new Date(2026, 0, 1, 22, 30), 22, 23), true);
});

test('isNight handles a window that wraps midnight', () => {
    // Night window 22:00-06:00.
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), 22, 6), true);
    assert.equal(isNight(new Date(2026, 0, 1, 0, 30), 22, 6), true);
    assert.equal(isNight(new Date(2026, 0, 1, 5, 59), 22, 6), true);
    assert.equal(isNight(new Date(2026, 0, 1, 6, 0), 22, 6), false);
    assert.equal(isNight(new Date(2026, 0, 1, 12, 0), 22, 6), false);
});

// The shape that actually ships: server/config.json spells night_start /
// night_end as "HH:MM", and T1.2's payload carries night:{start,end} the same
// way. Passing those strings to an hour-integer implementation returns false
// for every hour of the day, silently, so the night profile never engages.
test('isNight accepts the "HH:MM" strings the server config actually ships', () => {
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), '22:00', '07:00'), true);
    assert.equal(isNight(new Date(2026, 0, 1, 2, 0), '22:00', '07:00'), true);
    assert.equal(isNight(new Date(2026, 0, 1, 6, 59), '22:00', '07:00'), true);
    assert.equal(isNight(new Date(2026, 0, 1, 7, 0), '22:00', '07:00'), false);
    assert.equal(isNight(new Date(2026, 0, 1, 12, 0), '22:00', '07:00'), false);
});

test('isNight honours minutes rather than rounding down to the hour', () => {
    assert.equal(isNight(new Date(2026, 0, 1, 22, 15), '22:30', '07:00'), false);
    assert.equal(isNight(new Date(2026, 0, 1, 22, 30), '22:30', '07:00'), true);
    assert.equal(isNight(new Date(2026, 0, 1, 7, 29), '22:30', '07:30'), true);
    assert.equal(isNight(new Date(2026, 0, 1, 7, 30), '22:30', '07:30'), false);
});

test('isNight returns false for an unparseable bound instead of guessing', () => {
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), '22h00', '07:00'), false);
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), '25:00', '07:00'), false);
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), null, '07:00'), false);
    assert.equal(isNight(new Date(2026, 0, 1, 23, 0), '22:00', '22:00'), false);
});

// The one property this predicate shares with its twin in Java. T6.4 needs
// the same answer in two languages -- format.js dims the glow, NightWindow
// dims the backlight, and neither can reach the other's mechanism -- so the
// agreement is asserted on both sides in the same shape rather than left to
// two lists of examples that drift apart. NightWindowTest counts 540 too.
//
// A count over a whole day also catches what the examples above cannot: an
// off-by-one at either bound moves it by exactly one.
test('the shipped window is night for exactly the nine hours it names', () => {
    // A clock rather than a Date, and that is not a shortcut. Walking a real
    // Date through 1440 minutes walks it through whatever daylight-saving
    // transition the host's timezone puts on the day chosen, and the count
    // then comes out one hour wrong in some zones and not others -- which is
    // the shape of failure wave 15 spent a review on. isNight asks a clock
    // for its hours and its minutes and nothing else, so this is every input
    // it can see.
    const clock = (minute) => ({
        getHours: () => Math.floor(minute / 60),
        getMinutes: () => minute % 60,
    });
    let covered = 0;
    for (let minute = 0; minute < 24 * 60; minute += 1) {
        if (isNight(clock(minute), '22:00', '07:00')) {
            covered += 1;
        }
    }
    assert.equal(covered, 9 * 60);
});

// mock.js deliberately carries a sub-1 crypto price (and keeps six decimals
// for it) to prove the layout survives one. Truncating to two decimals shows
// it as 0.00 on every tick, hiding both the price and any movement in it.
test('formatPrice keeps sub-1 crypto prices visible instead of rounding to zero', () => {
    assert.equal(formatPrice(0.00081, 'USD'), '$0.00081');
    assert.equal(formatPrice(0.4212, 'USD'), '$0.4212');
    assert.equal(formatPrice(0.00000012, 'USD'), '$0.00000012');
});

test('formatPrice still uses exactly two decimals at or above 1', () => {
    assert.equal(formatPrice(341200, 'USD'), '$341,200.00');
    assert.equal(formatPrice(38.42, 'BRL'), 'R$38.42');
    assert.equal(formatPrice(1, 'USD'), '$1.00');
    assert.equal(formatPrice(0, 'USD'), '$0.00');
});

// An FX rate is not a price, and formatPrice gets one wrong in both
// directions: it truncates USD/BRL at 5.1434 to R$5.14, and it opens the
// sub-1 window meant for cheap crypto on CNY/BRL at 0.76749533, which
// rendered as R$0.76749533 and pushed its own label out of the column. Both
// were on the panel; the yuan is what made it visible.
test('formatRate keeps three decimals regardless of magnitude', () => {
    assert.equal(formatRate(5.1434, 'BRL'), 'R$5.143');
    assert.equal(formatRate(0.76749533, 'BRL'), 'R$0.767');
    assert.equal(formatRate(1, 'BRL'), 'R$1.000');
    // The width is the point: every rendering is the same length.
    assert.equal(formatRate(5.5, 'BRL').length, formatRate(5.1434, 'BRL').length);
});

test('formatRate returns a placeholder for non-numeric input', () => {
    assert.equal(formatRate(NaN, 'BRL'), '--');
    assert.equal(formatRate(undefined, 'BRL'), '--');
});

// The card already says R$ on every value, so repeating the quote currency in
// every label spends a third of the column saying the same thing three times.
test('formatPair drops the quote half when the card is denominated in it', () => {
    assert.equal(formatPair('USD/BRL', 'BRL'), 'USD');
    assert.equal(formatPair('CNY/BRL', 'BRL'), 'CNY');
});

test('formatPair keeps both halves when the quote differs from the card', () => {
    assert.equal(formatPair('EUR/USD', 'BRL'), 'EUR/USD');
});

test('formatPair passes through anything that is not a pair', () => {
    assert.equal(formatPair('USD', 'BRL'), 'USD');
    assert.equal(formatPair(undefined, 'BRL'), '');
});

// The sparkline is a picture, and a picture can lie in ways a number cannot.
// These pin the two ways this one could.
test('sparklinePath scales to the series own range, not to zero', () => {
    // A currency that moved 0.4% is a flat line against a zero baseline and a
    // legible shape against its own min and max. The trend is what the row is
    // for; the magnitude is already in the price beside it.
    const path = sparklinePath([5.12, 5.13, 5.11, 5.14], 56, 16);
    assert.match(path, /^M0,/);
    // The lowest value touches the bottom inset and the highest the top.
    assert.ok(path.includes('15'), `expected the low to reach the floor: ${path}`);
    assert.ok(path.includes(',1'), `expected the high to reach the ceiling: ${path}`);
});

test('sparklinePath spans the full width', () => {
    const path = sparklinePath([1, 2, 3], 56, 16);
    assert.ok(path.startsWith('M0,'), path);
    assert.ok(path.includes('L56,'), path);
});

test('sparklinePath draws a flat series as a centred line rather than dividing by zero', () => {
    const path = sparklinePath([5, 5, 5], 56, 16);
    assert.ok(!path.includes('NaN'), path);
    assert.equal(path, 'M0,8 L28,8 L56,8');
});

test('sparklinePath draws a single point as a flat line, so the row keeps its shape', () => {
    assert.equal(sparklinePath([5], 56, 16), 'M0,8 L56,8');
});

test('sparklinePath returns nothing to draw for nothing to draw', () => {
    assert.equal(sparklinePath([], 56, 16), '');
    assert.equal(sparklinePath(undefined, 56, 16), '');
    assert.equal(sparklinePath('nope', 56, 16), '');
});

test('sparklinePath ignores non-numeric entries instead of drawing NaN', () => {
    const path = sparklinePath([1, null, 3, 'x'], 56, 16);
    assert.ok(!path.includes('NaN'), path);
});

// The server returns null rather than 0 for a missing temperature, because
// zero is a real reading in most of the world. That is only honest if the page
// renders the null as an absence -- it used to interpolate it, and the panel
// read "São Paulo: 24°C (null-null°C)".
test('formatTemp renders a missing temperature as a dash', () => {
    assert.equal(formatTemp(null), '--');
    assert.equal(formatTemp(undefined), '--');
    assert.equal(formatTemp(NaN), '--');
});

test('formatTemp keeps one decimal and does not round a real zero away', () => {
    assert.equal(formatTemp(24), '24');
    assert.equal(formatTemp(15.5), '15.5');
    assert.equal(formatTemp(0), '0');
    assert.equal(formatTemp(-3.2), '-3.2');
});

// --- The battery line (T5.4; under the date since T6.12) ------------------
//
// This is a diagnostic, so the thing worth testing is that it never says
// something confidently wrong: a missing reading has to read as missing, and
// the temperature has to keep the tenth the broadcast carries.

// T6.10: the corner draws a battery and a thermometer instead of writing BAT
// and a degree sign, so the theme needs the pieces rather than the sentence.
// formatBattery composes its string out of these, which is what stops the two
// disagreeing about what the line says.
test('batteryFields hands a theme the three pieces of the line', () => {
    assert.deepEqual(batteryFields({ level: 87, tempC: 31.5, charging: true }),
                     { level: '87%', temp: '31.5\u00B0C', unplugged: false });
});

test('batteryFields reports unplugged only when the phone said so', () => {
    // `=== false`, not `!charging`: a payload with no charging key has not
    // said the phone is on battery, and the corner must not claim it has.
    assert.equal(batteryFields({ level: 50, tempC: 30, charging: false }).unplugged, true);
    assert.equal(batteryFields({ level: 50, tempC: 30, charging: true }).unplugged, false);
    assert.equal(batteryFields({ level: 50, tempC: 30 }).unplugged, false);
});

test('batteryFields says null when there is nothing worth a corner', () => {
    // Distinct from a row of absences: the panel shows an empty corner before
    // the first battery broadcast, not a battery icon beside a dash.
    assert.equal(batteryFields(null), null);
    assert.equal(batteryFields({}), null);
    assert.equal(batteryFields({ level: NaN }), null);
    assert.equal(batteryFields({ level: '87' }), null);
});

test('batteryFields separates an absent temperature from a zero one', () => {
    assert.equal(batteryFields({ level: 87, charging: true }).temp, null);
    // Zero is a temperature and not an absence -- a phone outdoors in winter.
    assert.equal(batteryFields({ level: 87, tempC: 0, charging: true }).temp, '0\u00B0C');
});

test('formatBattery is built from the same fields, so the two cannot drift', () => {
    const battery = { level: 64, tempC: 29, charging: false };
    const fields = batteryFields(battery);
    const text = formatBattery(battery);
    assert.ok(text.includes(fields.level), text);
    assert.ok(text.includes(fields.temp), text);
});

test('formatBattery writes the level, the temperature and its own label', () => {
    assert.equal(formatBattery({ level: 87, tempC: 31.5, charging: true }),
                 'BAT 87% \u00B7 31.5\u00B0C');
});

test('formatBattery spells out only the interesting half of charging', () => {
    // Charging is the resting state on a desk powered from the PC's USB, so it
    // costs the line no width; running on the battery is the condition worth a
    // word -- in the panel's language, which is the point of T6.11.
    assert.equal(formatBattery({ level: 64, tempC: 29, charging: false }),
                 'BAT 64% \u00B7 29\u00B0C \u00B7 na bateria');
    assert.equal(formatBattery({ level: 64, tempC: 29, charging: false }, 'en'),
                 'BAT 64% \u00B7 29\u00B0C \u00B7 unplugged');
});

test('formatBattery drops a temperature it was not given', () => {
    // The native side leaves tempC out rather than sending a zero, the same
    // way the server does for weather. -0.1 degrees from a missing extra is
    // exactly the kind of wrong that looks right enough to render.
    assert.equal(formatBattery({ level: 87, charging: true }), 'BAT 87%');
    assert.equal(formatBattery({ level: 87, tempC: null, charging: true }), 'BAT 87%');
});

test('formatBattery renders nothing at all before the first broadcast', () => {
    // '' rather than a placeholder: app.js appends no element for '', so the
    // corner is genuinely empty instead of holding an empty box.
    assert.equal(formatBattery(undefined), '');
    assert.equal(formatBattery(null), '');
    assert.equal(formatBattery({}), '');
    assert.equal(formatBattery({ level: NaN, tempC: 31.5 }), '');
});

test('formatBattery keeps the level a whole percent', () => {
    assert.equal(formatBattery({ level: 86.6, tempC: 30, charging: true }),
                 'BAT 87% \u00B7 30\u00B0C');
});

test('tempClass warms above forty degrees and not at it', () => {
    assert.equal(BATTERY_WARN_C, 40);
    assert.equal(tempClass(42.5), 'warm');
    assert.equal(tempClass(40.1), 'warm');
    assert.equal(tempClass(40), 'normal');
    assert.equal(tempClass(31.5), 'normal');
});

test('tempClass reddens before the screen blanks, not as it blanks', () => {
    // The ramp exists to warn, so the red band has to open below the cutoff.
    // If these two were equal the panel would go from amber straight to black
    // and the colour would have told the owner nothing (ADR 0012).
    assert.ok(BATTERY_HOT_C < 45, 'the hot band must open below the 45 cutoff');
    assert.equal(tempClass(BATTERY_HOT_C), 'hot');
    assert.equal(tempClass(44.9), 'hot');
    assert.equal(tempClass(46), 'hot');
    assert.equal(tempClass(42.9), 'warm');
});

test('tempClass treats a missing temperature as normal', () => {
    // A warning the panel cannot justify is worse than no warning: there is no
    // number beside it to explain the colour.
    assert.equal(tempClass(undefined), 'normal');
    assert.equal(tempClass(null), 'normal');
    assert.equal(tempClass(NaN), 'normal');
    assert.equal(tempClass('43'), 'normal');
});

// --- T6.6: the slow scroll, and when there must not be one ------------------

test('overflowsBy counts nothing hidden when the rows exactly fill the card', () => {
    // The boundary in the direction that must NOT move. A card that scrolls
    // with everything already on screen is motion for its own sake, in
    // someone's peripheral vision, all day.
    assert.equal(overflowsBy(5, 5), 0);
    assert.equal(overflowsBy(2, 5), 0);
    assert.equal(overflowsBy(0, 5), 0);
});

test('overflowsBy counts the rows one more than fits leaves hidden', () => {
    assert.equal(overflowsBy(6, 5), 1);
    assert.equal(overflowsBy(9, 3), 6);
});

test('overflowsBy takes a fractional measurement conservatively', () => {
    // The theme measures pixels and divides, so visibleRows arrives fractional.
    // 4.9 rows of room shows four rows, not five: half a row is not readable,
    // and rounding it up would leave the last row permanently cut in half at
    // the bottom of the card with nothing moving to reveal it.
    assert.equal(overflowsBy(5, 4.9), 1);
    assert.equal(overflowsBy(5, 5.1), 0);
});

test('overflowsBy treats an unusable measurement as no overflow', () => {
    // Fail still. A card that started moving because a measurement came back
    // NaN would be a thing flickering in the corner of the eye with no way to
    // tell what it was for.
    assert.equal(overflowsBy(NaN, 5), 0);
    assert.equal(overflowsBy(6, NaN), 0);
    assert.equal(overflowsBy(undefined, undefined), 0);
});

test('scrollPlan says do not scroll at the boundary, and does one row past it', () => {
    assert.equal(scrollPlan(5, 5, 16), null);
    const plan = scrollPlan(6, 5, 16);
    assert.equal(plan.hidden, 1);
});

test('a pass is the whole list, not the hidden part of it', () => {
    // T6.9 turned the card round: it used to walk down as far as the hidden
    // rows and come back, and it now goes round and round past a seam the
    // theme has made invisible by drawing the list twice. So the pass is the
    // list, and two cards showing nine rows move at the same speed whether
    // one row is hidden or five -- which is what somebody watching the panel
    // would expect, and was not true before.
    assert.equal(scrollPlan(9, 3, 16).seconds, 9 * 16);
    assert.equal(scrollPlan(9, 8, 16).seconds, 9 * 16);
    // And the hidden count is still what decides whether to move at all.
    assert.equal(scrollPlan(9, 3, 16).hidden, 6);
    assert.equal(scrollPlan(9, 8, 16).hidden, 1);
});

test('the shipped speed is a quarter of what T6.6 scrolled at', () => {
    // The one number this change is actually about, pinned so that "a quarter"
    // is a claim with a check under it rather than a sentence in a commit
    // message. Speed in pixels per second is rowHeight / secondsPerRow on
    // either design -- T6.6 spent 4s of *travel* per hidden row, and this
    // spends 16s per row of a pass that travels the whole list -- so the two
    // are comparable by this constant alone.
    assert.equal(SCROLL_SECONDS_PER_ROW, 16);
});

test('scrollPlan falls back to its own number when the theme sets none', () => {
    // getComputedStyle on a custom property a theme never declared parses to
    // NaN, which must not become a NaN-second animation.
    const plan = scrollPlan(6, 5, NaN);
    assert.equal(plan.seconds, 6 * SCROLL_SECONDS_PER_ROW);
    assert.deepEqual(scrollPlan(6, 5, 0), plan);
    assert.deepEqual(scrollPlan(6, 5, -4), plan);
});

test('a refresh that changes no rows produces the identical plan, so the scroll is not reset', () => {
    // This is step 4 of T6.6, stated where it can be tested. window.onData
    // replaces every row in the card every 60s; the scroll survives that for
    // two reasons, and this is the second of them.
    //
    // The first is structural and lives in the themes: the animation is on a
    // .scroller that mount() builds once and render() only refills, and
    // replacing an element's children does not disturb its animation.
    //
    // The second is this. The theme rewrites --scroll-seconds and
    // --scroll-distance on every render, and a CSS animation whose declaration
    // changes mid-flight jumps. An unchanged symbol set means an unchanged row
    // count, and an unchanged row count has to mean a byte-identical plan --
    // no clock, no random, no accumulating state. A plan that drifted by a
    // hundredth of a second per refresh would rewrite the declaration once a
    // minute, for ever.
    const before = scrollPlan(9, 3.4, 16);
    const after = scrollPlan(9, 3.4, 16);
    assert.deepEqual(after, before);
    // And the card that stopped overflowing stops moving, rather than keeping
    // an animation with a stale distance.
    assert.equal(scrollPlan(3, 3.4, 16), null);
});

// --- T6.8: the weather card -------------------------------------------------

test('formatRange joins two positive temperatures readably', () => {
    assert.equal(formatRange(18, 27), '18° / 27°');
});

test('formatRange is unambiguous when the low is negative', () => {
    // The bug. The card joined two formatTemp calls with a hyphen, so the
    // stress payload rendered `(-12-42°C)` -- a string nobody can parse by
    // eye, and it was on screen in e2e/layout/stress.js. A test that only
    // covered positives would have passed against it.
    assert.equal(formatRange(-12, 42), '-12° / 42°');
});

test('formatRange is unambiguous when both temperatures are negative', () => {
    assert.equal(formatRange(-12, -3), '-12° / -3°');
});

test('formatRange keeps a real zero, which is a temperature and not an absence', () => {
    assert.equal(formatRange(0, 8), '0° / 8°');
    assert.equal(formatRange(-4, 0), '-4° / 0°');
});

test('formatRange renders a missing bound as an absence, without a unit on it', () => {
    // Not `--°`, which is a temperature of nothing-degrees and is the same kind
    // of unparseable string this function exists to stop.
    assert.equal(formatRange(null, 27), '-- / 27°');
    assert.equal(formatRange(18, null), '18° / --');
    assert.equal(formatRange(null, null), '--');
    assert.equal(formatRange(undefined, undefined), '--');
});

test('weatherGlyph names a picture for every code the panel can label', () => {
    // Every code in the WMO table gets a glyph from the closed set. A code
    // that fell through to 'unknown' here would be a condition the card can
    // name in words and cannot draw, which is a gap worth failing on.
    const NAMES = new Set(['clear', 'cloudy', 'rain', 'snow', 'storm', 'fog']);
    const labels = LANGUAGES[FALLBACK_LANGUAGE].weather;
    for (const code of Object.keys(labels)) {
        const name = weatherGlyph(Number(code));
        assert.ok(NAMES.has(name),
                  `code ${code} (${labels[code]}) mapped to ${name}`);
    }
});

test('weatherGlyph has a defined answer for a code nobody has seen yet', () => {
    // open-meteo can add a code after this was written. 'unknown' is a real
    // member of the set -- the theme draws no glyph for it and the label still
    // says what it is -- and it must never be undefined, which would render as
    // an empty box.
    assert.equal(weatherGlyph(9999), 'unknown');
    assert.equal(weatherGlyph(undefined), 'unknown');
    assert.equal(weatherGlyph(null), 'unknown');
});

test('worthScrolling refuses a travel a pair of roundings could have invented', () => {
    // The device lays out at dpr 2.75 and clientHeight/scrollHeight are
    // integers, so a card whose rows exactly fill it can measure a pixel over.
    // A card that declared a scroll for that would hold a compositor layer and
    // move for as long as the panel is on to reveal a pixel, and every check
    // in e2e/layout would pass it: 1px is a real overflow as far as a
    // measurement can tell.
    assert.equal(worthScrolling(1, 26), false);
    assert.equal(worthScrolling(2, 26), false);
    assert.equal(worthScrolling(0, 26), false);
});

test('worthScrolling refuses a few pixels of phantom overflow on a real row', () => {
    // **The case the review of T6.9 found**, and it is the same case as above
    // with the price raised. The old design walked as far as the hidden pixels
    // and came back, so five pixels of phantom overflow bought five pixels of
    // twitch and a flat four-pixel floor was generous enough. The card goes
    // round now: any overflow at all walks the whole list past the window for
    // ever, so five pixels buys a card in permanent motion to reveal five
    // pixels. Half a row is the floor, and 5 over a 26px row is under it.
    assert.equal(worthScrolling(5, 26), false);
    assert.equal(worthScrolling(12, 26), false);
    assert.equal(worthScrolling(13, 26), true);
});

test('worthScrolling allows anything a genuinely hidden row could be', () => {
    assert.equal(worthScrolling(26, 26), true);
    assert.equal(worthScrolling(184, 26), true);
    // Two lines a row, as the plain theme draws them.
    assert.equal(worthScrolling(48, 48), true);
});

test('worthScrolling falls back to the flat floor when a row cannot be measured', () => {
    // rowHeight is 0 when there are no rows to divide by, and the themes hand
    // that through rather than guarding at the call site. A bare pixel count
    // is then the best answer available, which is what this used to be.
    assert.equal(worthScrolling(SCROLL_MIN_TRAVEL_PX, 0), true);
    assert.equal(worthScrolling(SCROLL_MIN_TRAVEL_PX - 1, 0), false);
    assert.equal(worthScrolling(20, NaN), true);
    assert.equal(worthScrolling(20, undefined), true);
});

test('the floor is half a row, stated where it can fail', () => {
    // Half rather than a whole one, because the count that decides *whether*
    // to scroll is already rows (overflowsBy): this is the second question,
    // and refusing a card that really is hiding most of a row would be the
    // opposite mistake.
    assert.equal(SCROLL_MIN_HIDDEN_ROWS, 0.5);
});

test('worthScrolling treats an unusable measurement as not worth moving for', () => {
    assert.equal(worthScrolling(NaN, 26), false);
    assert.equal(worthScrolling(undefined, 26), false);
    // Infinity too: a measurement that came back unbounded is a broken
    // measurement, and the panel's answer to one is to stay still (the same
    // bargain overflowsBy takes with NaN).
    assert.equal(worthScrolling(Infinity, 26), false);
});

// --- The burn-in shift (T6.2) ----------------------------------------------
//
// The panel moves a few pixels every few minutes so that one unchanging layout
// does not etch itself into an AMOLED (ADR 0008). All of the decision is
// offsetFor, and it is a pure function of the clock for exactly this reason:
// the alternative to these assertions is watching a screen for half an hour.

// Any time on any day, as a Date, so a case reads as a clock rather than as
// arithmetic. The date is arbitrary -- offsetFor only looks at the time.
function at(hours, minutes, seconds = 0) {
    return new Date(2026, 8, 20, hours, minutes, seconds);
}

// The first instant of a step, at or after `at(0, 0)`.
//
// Steps are counted from the epoch, so a step boundary is a multiple of the
// step length in UTC -- and local midnight is only one of those in a zone
// whose offset happens to divide by the step. Anchoring a "holds for the
// whole step" loop to a wall-clock hour therefore passes in UTC and in -03 and
// fails in +05:30, where midnight lands two minutes into a step. It did:
// `TZ=Asia/Kolkata node --test` was 63 of 64 before this.
function stepBoundary(extraSteps = 0) {
    const stepMs = BURN_IN_STEP_MINUTES * 60 * 1000;
    const start = Math.ceil(at(0, 0).getTime() / stepMs) * stepMs;
    return new Date(start + extraSteps * stepMs);
}

test('offsetFor holds one position for the whole of a step', () => {
    // One minute on one offset is the promise; a shift that changed with the
    // minute would be a panel twitching six times an hour more than it needs
    // to, and one that changed with the second would be an animation.
    const start = stepBoundary();
    const first = offsetFor(start);
    for (let second = 0; second < BURN_IN_STEP_MINUTES * 60; second += 1) {
        assert.deepEqual(offsetFor(new Date(start.getTime() + second * 1000)), first,
                         `${second}s into a step is a different position`);
    }
    // And the second after it is not this one, so the loop above is measuring
    // a boundary rather than a function that never changes at all.
    assert.notDeepEqual(offsetFor(stepBoundary(1)), first);
});

test('offsetFor moves to a different position at the next step', () => {
    // True from any starting instant, boundary or not: one step later is one
    // index later whatever the phase.
    assert.notDeepEqual(offsetFor(at(0, BURN_IN_STEP_MINUTES)), offsetFor(at(0, 0)));
});

test('every step in the cycle moves exactly one pixel, the wrap included', () => {
    // The headline property of T6.14 and the reason the table was replaced. A
    // four-pixel step is visible: it was reported from the chair as "uma
    // pulada" and then measured on the device, the whole panel moving (-8, +2)
    // physical pixels between two screenshots.
    //
    // The wrap is the half that is easy to lose. A path whose twenty positions
    // are each one pixel from the last is easy to write; getting the last
    // position back to the first in one pixel is what forces the band to have
    // an even side, because a closed tour of an odd number of nodes on a grid
    // cannot exist. A version of this table without the wrap step checked would
    // have jolted once per cycle instead of four times an hour, which is
    // exactly the kind of "mostly fixed" this assertion exists to refuse.
    const n = BURN_IN_OFFSETS.length;
    for (let i = 0; i < n; i += 1) {
        const a = BURN_IN_OFFSETS[i];
        const b = BURN_IN_OFFSETS[(i + 1) % n];
        const distance = Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
        assert.equal(distance, 1,
                     `step ${i} -> ${(i + 1) % n} moves ${distance}px, `
                     + `from (${a.x}, ${a.y}) to (${b.x}, ${b.y})`);
    }
});

test('the cycle has no resting bias, and uses the whole of each band', () => {
    // Both halves of this were once a comment beside BURN_IN_OFFSETS and
    // neither was true: seven entries cannot use five values once each, and the
    // y column summed to -13 rather than -14. A property worth stating is a
    // property worth asserting.
    //
    // The bands are no longer the same size in both axes -- 5 wide by 4 tall,
    // for the reason the table's comment gives -- so each axis's band is taken
    // from the table rather than from BURN_IN_AMPLITUDE_PX, and the amplitude
    // is asserted separately below as the bound it actually is.
    for (const axis of ['x', 'y']) {
        const values = BURN_IN_OFFSETS.map((o) => o[axis]);
        const low = Math.min(...values);
        const mean = values.reduce((a, b) => a + b, 0) / values.length;
        // Within a fifth of a pixel of the middle of the band, not exactly on
        // it: the cycle's one-pixel detour visits two positions twice. A table
        // that hit the midpoints exactly needed 26 steps and a dwell three
        // times longer on some positions than others, which is worse for the
        // thing the shift is for.
        assert.ok(Math.abs(mean - low / 2) <= 0.2,
                  `the ${axis} column sits at ${mean}, not near the band's `
                  + `midpoint of ${low / 2}`);
        // And every position in the band is visited by something in the cycle.
        for (let v = 0; v >= low; v -= 1) {
            assert.ok(values.includes(v), `no offset has ${axis} = ${v}`);
        }
        assert.ok(low >= -BURN_IN_AMPLITUDE_PX,
                  `the ${axis} band reaches ${low}, outside the amplitude`);
    }
});

test('the cycle visits twenty distinct positions in twenty-two steps', () => {
    // Not all distinct any more, and the difference is deliberate rather than
    // sloppy: a closed one-pixel tour of the band is twenty steps long, twenty
    // minutes divides a day, and the panel would then stand at the same offset
    // at the same time every day -- which is the mitigation turning into a
    // rota. The two extra steps are a one-pixel detour, so the cycle length
    // stops dividing 1440 without any step growing.
    const keys = new Set(BURN_IN_OFFSETS.map((o) => o.x + ',' + o.y));
    assert.equal(keys.size, 20, 'the table should cover the whole 5x4 band');
    assert.equal(BURN_IN_OFFSETS.length, 22);
    // The duplicates are the detour and nothing else: exactly two positions
    // appear twice, and they are one pixel apart.
    const counts = new Map();
    for (const o of BURN_IN_OFFSETS) {
        const k = o.x + ',' + o.y;
        counts.set(k, (counts.get(k) || 0) + 1);
    }
    const twice = [...counts.entries()].filter(([, c]) => c === 2).map(([k]) => k);
    assert.equal(twice.length, 2, `positions visited twice: ${twice.join(' ')}`);
    assert.ok([...counts.values()].every((c) => c <= 2),
              'no position may be visited more than twice');
    const [a, b] = twice.map((k) => k.split(',').map(Number));
    assert.equal(Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]), 1,
                 'the two repeated positions are not a one-pixel detour');
});

test('offsetFor repeats after a full cycle and not before', () => {
    const cycle = BURN_IN_OFFSETS.length * BURN_IN_STEP_MINUTES;
    const start = offsetFor(at(0, 0));
    assert.deepEqual(offsetFor(at(0, cycle)), start);
    // And the whole band is walked on the way round: twenty distinct positions
    // out of twenty-two steps, the two extra being the one-pixel detour that
    // keeps the cycle length from dividing a day.
    const seen = new Set();
    for (let m = 0; m < cycle; m += BURN_IN_STEP_MINUTES) {
        const o = offsetFor(at(0, m));
        seen.add(o.x + ',' + o.y);
    }
    assert.equal(seen.size, 20);
});

test('offsetFor never pushes the panel down or right', () => {
    // Not a style rule. A transform past the bottom or right edge adds to the
    // document's scrollable overflow, which is the one thing the panel may not
    // have: check_layout.py's first question is "does the page scroll", and a
    // page that scrolls is a page with somewhere to hide a row (T6.6).
    //
    // Every minute of the day, not every step, so an offsets table edited into
    // a positive value fails here whatever the step length becomes.
    for (let minute = 0; minute < 24 * 60; minute += 1) {
        const o = offsetFor(at(Math.floor(minute / 60), minute % 60));
        assert.ok(o.x <= 0 && o.y <= 0,
                  `offset at minute ${minute} is (${o.x}, ${o.y}), which is not up-and-left`);
        assert.ok(o.x >= -BURN_IN_AMPLITUDE_PX && o.y >= -BURN_IN_AMPLITUDE_PX,
                  `offset at minute ${minute} is (${o.x}, ${o.y}), outside the amplitude`);
    }
});

test('offsetFor does not put the panel in the same place at the same time tomorrow', () => {
    // The one thing the task file asks for in a sentence: the cycle must not
    // itself settle into a pattern. The PC is on for roughly the same hours
    // every day, so a count that restarted at midnight would put every offset
    // under the same glyphs at the same hour for the life of the panel -- a
    // rota, not a mitigation. Counting from the epoch instead, a day is 1440
    // one-minute steps against a cycle of 22, and 1440 mod 22 is 10, so the
    // phase advances ten positions a night.
    //
    // **This test asserted the wrong thing and passed on one desk.** It
    // compared *offsets* day by day and required all of them to differ until
    // the cycle returned. Two positions in the table are visited twice -- the
    // one-pixel detour that keeps the cycle length from dividing a day -- so
    // two days' advance of 20 steps is a step of -2, and for the four phases
    // that land on a repeated index the offset after two days is genuinely the
    // same one. The review found it by running the suite in another timezone:
    // green in America/Sao_Paulo, red in Europe/Lisbon and Pacific/Chatham,
    // because `at(9, 0)` is a local instant and which index it lands on
    // depends on the machine's zone.
    //
    // So the property is asserted where it is true -- on the cycle index, which
    // advances every day without exception -- plus the two things that actually
    // matter for the display: the panel is not where it was yesterday, and it
    // visits most of the band across the days before the phase returns.
    const cycle = BURN_IN_OFFSETS.length * BURN_IN_STEP_MINUTES;
    assert.notEqual((24 * 60) % cycle, 0);

    const gcd = (a, b) => (b === 0 ? a : gcd(b, a % b));
    const advance = (24 * 60) % cycle;
    const days = BURN_IN_OFFSETS.length / gcd(advance, BURN_IN_OFFSETS.length);
    assert.ok(days > 1, 'the panel stands in the same place every day');

    // The index, not the offset: a step of the cycle is a step of the cycle
    // whatever two of its entries happen to look alike.
    const indexAt = (date) => {
        const step = Math.floor(date.getTime() / (BURN_IN_STEP_MINUTES * 60000));
        return ((step % BURN_IN_OFFSETS.length) + BURN_IN_OFFSETS.length)
               % BURN_IN_OFFSETS.length;
    };
    const today = at(9, 0);
    const seen = new Set([indexAt(today)]);
    for (let day = 1; day < days; day += 1) {
        const later = new Date(today.getTime() + day * 24 * 60 * 60 * 1000);
        assert.notEqual(indexAt(later), indexAt(today),
                        `the cycle index is back where it started after ${day} day(s)`);
        seen.add(indexAt(later));
    }
    assert.equal(seen.size, days,
                 'the days before the phase returns should each be a different step');

    // Tomorrow is a different place on screen, which is the claim a reader
    // could check. This one *is* true of the offsets: the repeated pair is two
    // indices apart and a day advances ten, so no phase maps to its own
    // offset a day later.
    const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
    assert.notDeepEqual(offsetFor(tomorrow), offsetFor(today));

    // And across those days the panel really does move around the band rather
    // than alternating between two spots. Nine of the eleven steps land on
    // distinct offsets in the worst case, which is the number the repeated
    // pair costs.
    const offsets = new Set();
    for (let day = 0; day < days; day += 1) {
        const when = new Date(today.getTime() + day * 24 * 60 * 60 * 1000);
        const o = offsetFor(when);
        offsets.add(o.x + ',' + o.y);
    }
    assert.ok(offsets.size >= days - 2,
              `only ${offsets.size} distinct offsets across ${days} days`);

    // And it does come back, on the eleventh -- a cycle and not a drift. The
    // number is computed above rather than written here for the same reason.
    const returns = new Date(today.getTime() + days * 24 * 60 * 60 * 1000);
    assert.equal(indexAt(returns), indexAt(today),
                 `the cycle index should return after ${days} days`);
});

test('offsetFor answers the origin for a clock it cannot read', () => {
    // A panel that is merely not moving is a working panel; one that threw
    // inside host.tick would take the clock's repaint down with it, because the
    // shift runs before the theme's tick and outside its try (js/host.js).
    assert.deepEqual(offsetFor(new Date('not a date')), { x: 0, y: 0 });
    assert.deepEqual(offsetFor(undefined), { x: 0, y: 0 });
    assert.deepEqual(offsetFor(1758300000000), { x: 0, y: 0 });
});

test('offsetFor hands back a copy, so a caller cannot delete a position', () => {
    const when = at(0, 0);
    const was = offsetFor(when).x;
    offsetFor(when).x = 99;
    assert.equal(offsetFor(when).x, was);
});

test('burnInSchedule describes the same cycle offsetFor walks', () => {
    // e2e/layout/check_layout.py drives the panel through every offset in this
    // schedule and measures each. If it described a different cycle than the
    // one the page actually walks, the harness would be measuring positions
    // the panel never visits and missing the ones it does.
    const schedule = burnInSchedule();
    assert.equal(schedule.stepMinutes, BURN_IN_STEP_MINUTES);
    assert.equal(schedule.amplitudePx, BURN_IN_AMPLITUDE_PX);

    // Which offset is showing at a given moment is the clock's business, so
    // what the harness is promised is weaker and is the thing it relies on:
    // step the clock stepMinutes at a time, offsets.length times, from
    // anywhere, and you visit every position in this order -- rotated.
    const base = at(13, 7);
    const walked = schedule.offsets.map((_, i) => offsetFor(
        new Date(base.getTime() + i * BURN_IN_STEP_MINUTES * 60 * 1000)));
    const key = (o) => o.x + ',' + o.y;
    assert.deepEqual(new Set(walked.map(key)), new Set(schedule.offsets.map(key)));
    const start = schedule.offsets.findIndex((o) => key(o) === key(walked[0]));
    assert.ok(start >= 0);
    walked.forEach((offset, i) => {
        assert.deepEqual(offset, schedule.offsets[(start + i) % schedule.offsets.length]);
    });
});

test('burnInSchedule hands back copies of the table', () => {
    const was = burnInSchedule().offsets[0].x;
    burnInSchedule().offsets[0].x = 99;
    assert.equal(burnInSchedule().offsets[0].x, was);
});

// --- The moon and the night sky (T6.13) -------------------------------------
//
// The panel drew a **sun** for `Predominantemente limpo` at 21:20 with the
// window dark, which is where all of this came from. Two separate answers came
// out of it: the sky's glyph stops being a sun after dark, and the moon gets a
// permanent place on the card with its phase and how much of it is lit.

test('weatherGlyph only changes for the two codes that are about the sky', () => {
    // Rain at night is still rain, and this is the assertion that says so. The
    // temptation with a day/night flag is to give every code a second glyph;
    // the panel has seven pictures and six of them mean the same thing at both
    // hours.
    assert.equal(weatherGlyph(1, true), 'clear');
    assert.equal(weatherGlyph(1, false), 'stars');
    assert.equal(weatherGlyph(2, true), 'cloudy');
    assert.equal(weatherGlyph(2, false), 'cloudy-night');
    for (const code of [45, 63, 73, 99]) {
        assert.equal(weatherGlyph(code, false), weatherGlyph(code, true),
                     `code ${code} should look the same at both hours`);
    }
});

test('weatherGlyph treats an absent isDay as day', () => {
    // A server too old to send the field, or a body cached from before it
    // existed, has to behave exactly as it did. Absent means day in the
    // server's normalise too, and for the same reason: a sun at midnight was
    // the bug, and a moon at noon would be stranger.
    assert.equal(weatherGlyph(1), 'clear');
    assert.equal(weatherGlyph(1, undefined), 'clear');
    assert.equal(weatherGlyph(1, null), 'clear');
    // Only an explicit false is night. `0` is not: the server sends a real
    // boolean and anything else reaching here is a bug worth not hiding.
    assert.equal(weatherGlyph(1, 0), 'clear');
    assert.equal(weatherGlyph(1, false), 'stars');
});

test('moonFields derives waxing from the phase name, not from a flag', () => {
    const words = strings('pt-BR');
    const waxing = ['waxing-crescent', 'first-quarter', 'waxing-gibbous'];
    const waning = ['waning-gibbous', 'last-quarter', 'waning-crescent'];
    for (const phase of waxing) {
        assert.equal(moonFields({ phase, illum: 40 }, words).waxing, true, phase);
    }
    for (const phase of waning) {
        assert.equal(moonFields({ phase, illum: 40 }, words).waxing, false, phase);
    }
    // new and full have no lit limb to put on a side, so the flag is not
    // meaningful for either -- it must still be a boolean rather than throw.
    for (const phase of ['new', 'full']) {
        assert.equal(typeof moonFields({ phase, illum: 0 }, words).waxing,
                     'boolean', phase);
    }
});

test('moonFields refuses a phase it does not know', () => {
    // The server decides the name and this file decides what the name is
    // called, so a table that drifted would draw the wrong moon. null is what
    // makes the theme draw nothing instead of a shape with no meaning.
    const words = strings('pt-BR');
    assert.equal(moonFields({ phase: 'gibbous', illum: 50 }, words), null);
    assert.equal(moonFields({ illum: 50 }, words), null);
    assert.equal(moonFields(undefined, words), null);
    assert.equal(moonFields(null, words), null);
    assert.equal(moonFields('full', words), null);
});

test('moonFields clamps the illumination and survives it missing', () => {
    const words = strings('pt-BR');
    assert.equal(moonFields({ phase: 'full', illum: 140 }, words).illum, 100);
    assert.equal(moonFields({ phase: 'new', illum: -3 }, words).illum, 0);
    assert.equal(moonFields({ phase: 'full', illum: 83.6 }, words).illum, 84);
    // Missing is null and not zero. A moon with no percentage is still a moon
    // and the shape still says which phase it is; `0%` would be a claim.
    assert.equal(moonFields({ phase: 'full' }, words).illum, null);
    assert.equal(moonFields({ phase: 'full', illum: 'lots' }, words).illum, null);
});

test('formatPercent writes a whole percentage or nothing at all', () => {
    assert.equal(formatPercent(84), '84%');
    assert.equal(formatPercent(0), '0%');
    assert.equal(formatPercent(100), '100%');
    assert.equal(formatPercent(83.6), '84%');
    // Never `--%`: the dash pattern is right for a temperature, where the
    // number is the whole point, and wrong here where the shape carries it.
    assert.equal(formatPercent(null), null);
    assert.equal(formatPercent(undefined), null);
    assert.equal(formatPercent(NaN), null);
});

test('every language names all eight phases', () => {
    // The same rule the weather tables live under: a half-translated table
    // fails here rather than on a panel. The phase name is the glyph's
    // accessible label, and eight shapes at 22px cannot tell a waxing crescent
    // from a waning one -- which is the half somebody can check by looking up.
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        assert.ok(table.moon, `${tag} has no moon table`);
        for (const phase of MOON_PHASES) {
            assert.equal(typeof table.moon[phase], 'string',
                         `${tag} does not name ${phase}`);
            assert.ok(table.moon[phase].length > 0,
                      `${tag} names ${phase} as an empty string`);
        }
        assert.equal(Object.keys(table.moon).length, MOON_PHASES.length,
                     `${tag} has a moon key that is not a phase`);
    }
});

test('the phase order is the one a lunation actually visits', () => {
    // Asserted rather than described because the server has the same list and
    // the two must not drift: server/providers_usno.PHASE_NAMES is this array,
    // in this order, and server/tests/test_providers_usno.py walks a real
    // lunation to prove the server's copy. Waxing before full, waning after.
    assert.deepEqual(MOON_PHASES, [
        'new', 'waxing-crescent', 'first-quarter', 'waxing-gibbous',
        'full', 'waning-gibbous', 'last-quarter', 'waning-crescent',
    ]);
    assert.equal(MOON_PHASES.indexOf('full'), 4);
    assert.ok(MOON_PHASES.indexOf('waxing-gibbous') < MOON_PHASES.indexOf('full'));
    assert.ok(MOON_PHASES.indexOf('waning-gibbous') > MOON_PHASES.indexOf('full'));
});

// --- The chance of rain (T6.15) ---------------------------------------------

test('chanceOfRain clamps, rounds, and refuses anything that is not a number', () => {
    assert.equal(chanceOfRain({ precipProb: 98 }), 98);
    assert.equal(chanceOfRain({ precipProb: 0 }), 0);
    assert.equal(chanceOfRain({ precipProb: 7.4 }), 7);
    // Clamped rather than trusted. A panel drawing `140%` would be wrong in
    // the one way nobody reports, because it reads as a bad number rather
    // than as a bad panel.
    assert.equal(chanceOfRain({ precipProb: 140 }), 100);
    assert.equal(chanceOfRain({ precipProb: -5 }), 0);
    // Absent is null and not zero. `0%` is a forecast; a server too old to
    // send the field has not made one.
    assert.equal(chanceOfRain({}), null);
    assert.equal(chanceOfRain({ precipProb: null }), null);
    assert.equal(chanceOfRain({ precipProb: 'lots' }), null);
    assert.equal(chanceOfRain(undefined), null);
    assert.equal(chanceOfRain(null), null);
});

test('formatPercent serves the moon and the rain with one rule', () => {
    // One function for both, which is what the second caller made worth
    // asserting: the two numbers sit in a column on the card and must not be
    // formatted differently.
    assert.equal(formatPercent(84), '84%');
    assert.equal(formatPercent(98), '98%');
    assert.equal(formatPercent(0), '0%');
    assert.equal(formatPercent(null), null);
});

test('every language has a word for the chance of rain', () => {
    // Never drawn by the neon theme -- it is the drop's accessible name there,
    // because the ask was explicitly "sem palavra" -- and drawn in full by
    // plain, which has no pictures. So it is wording, and wording is
    // translated or the plain theme is half-English.
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        assert.equal(typeof table.rainChance, 'string', `${tag} has no rainChance`);
        assert.ok(table.rainChance.length > 0, `${tag} has an empty rainChance`);
    }
});


// --- The shortcut buttons (T8.2) -------------------------------------------

test('shortcutsFor keeps the order the PC sent', () => {
    // The server's config decides which buttons exist and in which order, so
    // a theme drawing them in its own order would make `actions` half a
    // setting.
    const got = shortcutsFor(['mute-mic', 'mute-audio'], 'en').map((s) => s.id);
    assert.deepEqual(got, ['mute-mic', 'mute-audio']);
});

test('shortcutsFor renders nothing for an id this build has no word for', () => {
    // T8.2 step 5. A button captioned `mute-everything` is a button nobody
    // can read, which is worse than the gap where one would be -- and it is
    // the state a PC running ahead of the APK puts the panel in.
    assert.deepEqual(shortcutsFor(['mute-everything'], 'en'), []);
    assert.deepEqual(shortcutsFor(['mute-audio', 'mute-everything'], 'en').map((s) => s.id),
                     ['mute-audio']);
});

test('shortcutsFor survives a payload that promises nothing', () => {
    // `actions` absent is an older server; `actions: []` is a panel whose
    // owner enabled none. Both draw no buttons, and neither may throw inside
    // a theme's render.
    for (const value of [undefined, null, [], 'mute-audio', 42, {}]) {
        assert.deepEqual(shortcutsFor(value, 'en'), [], String(value));
    }
});

test('shortcutsFor drops a repeat rather than drawing two of one button', () => {
    assert.deepEqual(shortcutsFor(['mute-mic', 'mute-mic'], 'en').map((s) => s.id),
                     ['mute-mic']);
});

test('shortcutsFor is translated, and the id is not', () => {
    // The id is an identifier and crosses the wire; the caption is what a
    // person reads. Getting that backwards is how an action id ends up
    // translated and the POST 404s.
    const [pt] = shortcutsFor(['mute-audio'], 'pt-BR');
    const [en] = shortcutsFor(['mute-audio'], 'en');
    assert.equal(pt.id, 'mute-audio');
    assert.equal(en.id, 'mute-audio');
    assert.notEqual(pt.label, en.label);
});

test('every language has a caption for every action and a hint', () => {
    // The same rule the rain chance is held to: a panel in another language
    // must not be half-English. Keyed off one table so a new action fails
    // here rather than shipping with one caption.
    const ids = Object.keys(LANGUAGES[FALLBACK_LANGUAGE].actions);
    assert.ok(ids.length > 0, 'no actions are named at all');
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        assert.equal(typeof table.actionHint, 'string', `${tag} has no actionHint`);
        assert.ok(table.actionHint.length > 0, `${tag} has an empty actionHint`);
        assert.equal(typeof table.actionFailed, 'string', `${tag} has no actionFailed`);
        for (const key of ['actionMuted', 'actionUnmuted']) {
            // Said to a screen reader after a press. Both have to carry "last
            // asked" in whatever words the language uses -- the panel knows a
            // state the PC reported, not a live one, and an accessible name
            // that claimed otherwise would be the lie the picture avoids.
            assert.equal(typeof table[key], 'string', `${tag} has no ${key}`);
            assert.ok(table[key].length > 0, `${tag} has an empty ${key}`);
        }
        assert.notEqual(table.actionMuted, table.actionUnmuted,
                        `${tag} says the same thing for muted and unmuted`);
        for (const id of ids) {
            assert.equal(typeof table.actions[id], 'string', `${tag} has no caption for ${id}`);
            assert.ok(table.actions[id].length > 0, `${tag} has an empty caption for ${id}`);
        }
        assert.deepEqual(Object.keys(table.actions).sort(), ids.slice().sort(),
                         `${tag} names a different set of actions`);
    }
});

test('the captions are short enough for a 56px button', () => {
    // Not a style opinion: the two buttons sit next to each other under the
    // clock and a caption that wraps or clips is a button somebody mis-taps.
    // Six characters is what fits at the size web/themes/*/theme.css draws.
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        for (const [id, caption] of Object.entries(table.actions)) {
            assert.ok(caption.length <= 6, `${tag} ${id} caption "${caption}" is too long`);
        }
    }
});

test('marketClosed only on an explicit false from the server', () => {
    assert.equal(marketClosed({ b3Open: false }), true);
    assert.equal(marketClosed({ b3Open: true }), false);
    // An older server sends no key, and that is not a shut market.
    assert.equal(marketClosed({}), false);
    assert.equal(marketClosed(null), false);
});
