'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    formatPrice, formatRate, formatPair, formatChange, changeClass, weatherLabel, isNight,
    sparklinePath, formatTemp, formatBattery, tempClass, BATTERY_WARN_C, BATTERY_HOT_C,
    formatRange, weatherGlyph, WEATHER_LABELS,
    overflowsBy, scrollPlan, worthScrolling,
    SCROLL_SECONDS_PER_ROW, SCROLL_MOVING_FRACTION, SCROLL_MIN_TRAVEL_PX,
    offsetFor, burnInSchedule,
    BURN_IN_OFFSETS, BURN_IN_STEP_MINUTES, BURN_IN_AMPLITUDE_PX,
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

test('weatherLabel maps a known WMO code', () => {
    assert.equal(weatherLabel(95), 'Thunderstorm');
});

test('weatherLabel falls back to Unknown for an unmapped code', () => {
    assert.equal(weatherLabel(9999), 'Unknown');
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

// --- The battery corner line (T5.4) ---------------------------------------
//
// This is a diagnostic, so the thing worth testing is that it never says
// something confidently wrong: a missing reading has to read as missing, and
// the temperature has to keep the tenth the broadcast carries.

test('formatBattery writes the level, the temperature and its own label', () => {
    assert.equal(formatBattery({ level: 87, tempC: 31.5, charging: true }),
                 'BAT 87% \u00B7 31.5\u00B0C');
});

test('formatBattery spells out only the interesting half of charging', () => {
    // Charging is the resting state on a desk powered from the PC's USB, so it
    // costs the line no width; running on the battery is the condition worth a
    // word.
    assert.equal(formatBattery({ level: 64, tempC: 29, charging: false }),
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
    assert.equal(scrollPlan(5, 5, 4, 0.7), null);
    const plan = scrollPlan(6, 5, 4, 0.7);
    assert.equal(plan.hidden, 1);
    // One hidden row travels for one row's worth of seconds; the cycle is
    // longer than the travel by whatever the keyframes hold at the two ends.
    assert.equal(plan.seconds, Math.round((4 / 0.7) * 100) / 100);
});

test('scrollPlan spends the theme seconds per hidden row', () => {
    // Six rows hidden at four seconds each is 24 seconds of travel, in a cycle
    // that also holds at both ends.
    const plan = scrollPlan(9, 3, 4, 0.7);
    assert.equal(plan.hidden, 6);
    assert.ok(Math.abs(plan.seconds * 0.7 - 24) < 0.05,
              `expected ~24s of travel, got ${plan.seconds * 0.7}`);
});

test('scrollPlan falls back to its own numbers when the theme sets none', () => {
    // getComputedStyle on a custom property a theme never declared parses to
    // NaN, which must not become a NaN-second animation.
    const plan = scrollPlan(6, 5, NaN, NaN);
    assert.equal(plan.seconds,
                 Math.round((SCROLL_SECONDS_PER_ROW / SCROLL_MOVING_FRACTION) * 100) / 100);
    assert.deepEqual(scrollPlan(6, 5, 0, 0), plan);
    assert.deepEqual(scrollPlan(6, 5, -4, 2), plan);
});

test('a refresh that changes no rows produces the identical plan, so the scroll is not reset', () => {
    // This is step 4 of the task, stated where it can be tested. window.onData
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
    const before = scrollPlan(9, 3.4, 4, 0.7);
    const after = scrollPlan(9, 3.4, 4, 0.7);
    assert.deepEqual(after, before);
    // And the card that stopped overflowing stops moving, rather than keeping
    // an animation with a stale distance.
    assert.equal(scrollPlan(3, 3.4, 4, 0.7), null);
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
    for (const code of Object.keys(WEATHER_LABELS)) {
        const name = weatherGlyph(Number(code));
        assert.ok(NAMES.has(name),
                  `code ${code} (${WEATHER_LABELS[code]}) mapped to ${name}`);
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
    // twitch one pixel every seventeen seconds for as long as the panel is on,
    // and every check in e2e/layout would pass it: 1px is a real overflow as
    // far as a measurement can tell.
    assert.equal(worthScrolling(1), false);
    assert.equal(worthScrolling(2), false);
    assert.equal(worthScrolling(0), false);
});

test('worthScrolling allows anything a genuinely hidden row could be', () => {
    // A row is twenty-odd pixels tall on either theme, so the floor is nowhere
    // near a real overflow.
    assert.equal(worthScrolling(SCROLL_MIN_TRAVEL_PX), true);
    assert.equal(worthScrolling(20), true);
    assert.equal(worthScrolling(184), true);
});

test('worthScrolling treats an unusable measurement as not worth moving for', () => {
    assert.equal(worthScrolling(NaN), false);
    assert.equal(worthScrolling(undefined), false);
    // Infinity too: a measurement that came back unbounded is a broken
    // measurement, and the panel's answer to one is to stay still (the same
    // bargain overflowsBy takes with NaN).
    assert.equal(worthScrolling(Infinity), false);
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
// whose offset happens to divide by four minutes. Anchoring a "holds for the
// whole step" loop to a wall-clock hour therefore passes in UTC and in -03 and
// fails in +05:30, where midnight lands two minutes into a step. It did:
// `TZ=Asia/Kolkata node --test` was 63 of 64 before this.
function stepBoundary(extraSteps = 0) {
    const stepMs = BURN_IN_STEP_MINUTES * 60 * 1000;
    const start = Math.ceil(at(0, 0).getTime() / stepMs) * stepMs;
    return new Date(start + extraSteps * stepMs);
}

test('offsetFor holds one position for the whole of a step', () => {
    // Four minutes on one offset is the promise; a shift that changed with the
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

test('the cycle has no resting bias, and uses the whole of its amplitude', () => {
    // Both halves of this were a comment beside BURN_IN_OFFSETS and neither was
    // true: seven entries cannot use five values once each, and the y column
    // summed to -13 rather than -14, so the ink spent slightly longer in the
    // lower half of the band than the table claimed. A property worth stating
    // is a property worth asserting -- it is the fourth time in this repo that
    // a claim with no check behind it has turned out to be wrong.
    for (const axis of ['x', 'y']) {
        const values = BURN_IN_OFFSETS.map((o) => o[axis]);
        const sum = values.reduce((a, b) => a + b, 0);
        // The mean sits exactly at the middle of [-amplitude, 0], so the panel
        // has no standing offset in either direction.
        assert.equal(sum * 2, -BURN_IN_AMPLITUDE_PX * BURN_IN_OFFSETS.length,
                     `the ${axis} column is not centred in the band`);
        // And every position in the band is visited by something in the cycle.
        for (let v = 0; v >= -BURN_IN_AMPLITUDE_PX; v -= 1) {
            assert.ok(values.includes(v), `no offset has ${axis} = ${v}`);
        }
    }
    // Distinct, which is what makes it seven positions rather than seven visits
    // to fewer.
    const keys = new Set(BURN_IN_OFFSETS.map((o) => o.x + ',' + o.y));
    assert.equal(keys.size, BURN_IN_OFFSETS.length);
});

test('offsetFor repeats after a full cycle and not before', () => {
    const cycle = BURN_IN_OFFSETS.length * BURN_IN_STEP_MINUTES;
    const start = offsetFor(at(0, 0));
    assert.deepEqual(offsetFor(at(0, cycle)), start);
    // Every position in between is a different one, which is what makes the
    // cycle seven positions rather than seven visits to fewer.
    const seen = new Set();
    for (let m = 0; m < cycle; m += BURN_IN_STEP_MINUTES) {
        const o = offsetFor(at(0, m));
        seen.add(o.x + ',' + o.y);
    }
    assert.equal(seen.size, BURN_IN_OFFSETS.length);
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
    // rota, not a mitigation. Counting from the epoch instead, a day is 360
    // steps against a cycle of seven and 360 mod 7 is 3, so the phase advances
    // three positions a night.
    //
    // This is the assertion that failed the first implementation, which did
    // index off minutes-of-day and passed every other test here.
    const cycle = BURN_IN_OFFSETS.length * BURN_IN_STEP_MINUTES;
    assert.notEqual((24 * 60) % cycle, 0);
    const today = at(9, 0);
    for (let day = 1; day < BURN_IN_OFFSETS.length; day += 1) {
        const later = new Date(today.getTime() + day * 24 * 60 * 60 * 1000);
        assert.notDeepEqual(offsetFor(later), offsetFor(today),
                            `the panel is back where it started after ${day} day(s)`);
    }
    // And it does come back, on the seventh -- this is a cycle and not a drift.
    const week = new Date(today.getTime()
                          + BURN_IN_OFFSETS.length * 24 * 60 * 60 * 1000);
    assert.deepEqual(offsetFor(week), offsetFor(today));
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
