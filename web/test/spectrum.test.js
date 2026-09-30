// T8.5: the spectrum bars' parsing and physics. The drawing is the theme's;
// what a bar does between frames is pinned here.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
    parseSpectrum, spectrumState, spectrumStep, spectrumAtRest,
    SPECTRUM_BARS, SPECTRUM_FALL_PER_S, SPECTRUM_PEAK_HOLD_MS,
} = require('../js/format.js');

const FULL = 'ff'.repeat(16);

test('a frame parses to sixteen levels from 0 to 1', () => {
    const bars = parseSpectrum('00ff80' + '00'.repeat(13));
    assert.equal(bars.length, SPECTRUM_BARS);
    assert.equal(bars[0], 0);
    assert.equal(bars[1], 1);
    assert.ok(Math.abs(bars[2] - 128 / 255) < 1e-9);
});

test('anything that is not exactly a frame is refused', () => {
    for (const bad of [null, undefined, 42, '', FULL.slice(2), FULL + '00',
                       FULL.toUpperCase(), 'zz'.repeat(16), "')".repeat(16)]) {
        assert.equal(parseSpectrum(bad), null, String(bad));
    }
});

test('a bar jumps up at once', () => {
    const next = spectrumStep(spectrumState(), parseSpectrum(FULL), 16);
    assert.equal(next.levels[0], 1);
    assert.equal(next.peaks[0], 1);
});

test('a bar falls at the fixed rate, not at once', () => {
    let s = spectrumStep(spectrumState(), parseSpectrum(FULL), 16);
    s = spectrumStep(s, parseSpectrum('00'.repeat(16)), 250);
    assert.ok(Math.abs(s.levels[0] - (1 - SPECTRUM_FALL_PER_S * 0.25)) < 1e-9);
    s = spectrumStep(s, null, 1000);
    assert.equal(s.levels[0], 0);
});

test('the cap holds at the peak, then falls, and never below its bar', () => {
    let s = spectrumStep(spectrumState(), parseSpectrum(FULL), 16);
    s = spectrumStep(s, null, SPECTRUM_PEAK_HOLD_MS - 50);
    assert.equal(s.peaks[0], 1);
    assert.ok(s.levels[0] < 1);
    s = spectrumStep(s, null, 200);
    assert.ok(s.peaks[0] < 1);
    assert.ok(s.peaks[0] >= s.levels[0]);
});

test('the step is pure', () => {
    const before = spectrumState();
    spectrumStep(before, parseSpectrum(FULL), 16);
    assert.deepEqual(before, spectrumState());
});

test('at rest only when every bar and cap is on the floor', () => {
    assert.equal(spectrumAtRest(spectrumState()), true);
    let s = spectrumStep(spectrumState(), parseSpectrum(FULL), 16);
    assert.equal(spectrumAtRest(s), false);
    for (let i = 0; i < 40; i++) {
        s = spectrumStep(s, null, 100);
    }
    assert.equal(spectrumAtRest(s), true);
});
