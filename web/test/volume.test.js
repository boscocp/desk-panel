// T8.6: the PC's volume riding the spectrum stream. The page takes a level
// only if it is an integer 0..100, and keeps it in the held payload so a later
// paint does not go back to the older number.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { parseVolume, withVolume, volumeFields } = require('../js/format.js');

const PAYLOAD = { actions: ['mute-audio', 'volume'], volume: { level: 100 }, quotes: [] };

test('an integer from 0 to 100 is a level', () => {
    assert.equal(parseVolume(0), 0);
    assert.equal(parseVolume(51), 51);
    assert.equal(parseVolume(100), 100);
});

test('anything else is not', () => {
    for (const bad of [null, undefined, -1, 101, 5.5, '51', NaN, Infinity, {}, [51]]) {
        assert.equal(parseVolume(bad), null, String(bad));
    }
});

test('the held payload takes the new level and the old one is left alone', () => {
    const next = withVolume(PAYLOAD, 51);
    assert.equal(next.volume.level, 51);
    assert.equal(PAYLOAD.volume.level, 100);
    assert.equal(volumeFields(next, 'en').level, 51);
    assert.deepEqual(next.actions, PAYLOAD.actions);
});

test('a bar that is not enabled stays not enabled', () => {
    const off = { actions: ['mute-audio'], volume: null };
    assert.equal(withVolume(off, 51), off);
    assert.equal(withVolume(null, 51), null);
});

test('a bad level changes nothing', () => {
    assert.equal(withVolume(PAYLOAD, 300), PAYLOAD);
});
