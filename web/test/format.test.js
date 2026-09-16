'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { formatPrice, formatChange, changeClass, weatherLabel, isNight } = require('../js/format.js');

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
