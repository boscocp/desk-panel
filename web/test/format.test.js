'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    formatPrice, formatRate, formatPair, formatChange, changeClass, weatherLabel, isNight,
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
    assert.equal(formatRate(1, 'BRL'), 'R$1.00');
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
