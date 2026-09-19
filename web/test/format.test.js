'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    formatPrice, formatRate, formatPair, formatChange, changeClass, weatherLabel, isNight,
    sparklinePath, formatTemp,
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
