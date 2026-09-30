// T9.5: the meeting alerts -- the bell and breath at `soon_min`, the chime at
// `chime_min`. Pure functions of (agenda, now); the chime-once rule lives in
// app.js and keys on what agendaAlert returns, so the key is pinned here.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { agendaAlert, agendaRows, agendaFields } = require('../js/format.js');

const NOW = new Date(2026, 8, 29, 13, 55, 0);
const ALERTS = { soon_min: 5, chime_min: 1, chime_volume: 0.4 };

function inMinutes(m, extra = {}) {
    const start = new Date(NOW.getTime() + m * 60000);
    const end = new Date(start.getTime() + 30 * 60000);
    return Object.assign({ start: start.toISOString(), end: end.toISOString(),
                           allDay: false, source: 'google/personal', title: 'Standup' }, extra);
}

function agenda(events, alerts = ALERTS) {
    return { accounts: 1, events, failed: [], alerts };
}

test('outside every window there is no alert', () => {
    assert.equal(agendaAlert(agenda([inMinutes(6)]), NOW), null);
});

test('inside soon_min it is soon, inside chime_min it is chime', () => {
    assert.equal(agendaAlert(agenda([inMinutes(5)]), NOW).level, 'soon');
    assert.equal(agendaAlert(agenda([inMinutes(2)]), NOW).level, 'soon');
    assert.equal(agendaAlert(agenda([inMinutes(1)]), NOW).level, 'chime');
    assert.equal(agendaAlert(agenda([inMinutes(0.25)]), NOW).level, 'chime');
});

test('a meeting that has started, or an all-day one, never alerts', () => {
    assert.equal(agendaAlert(agenda([inMinutes(-1)]), NOW), null);
    assert.equal(agendaAlert(agenda([inMinutes(0)]), NOW), null);
    assert.equal(agendaAlert(agenda([inMinutes(1, { allDay: true })]), NOW), null);
});

test('the key is the same meeting on every tick, and another meeting is another key', () => {
    const a = agendaAlert(agenda([inMinutes(1)]), NOW);
    const b = agendaAlert(agenda([inMinutes(1)]), new Date(NOW.getTime() + 20000));
    assert.equal(a.key, b.key);
    const other = agendaAlert(agenda([inMinutes(1, { title: 'Review' })]), NOW);
    assert.notEqual(a.key, other.key);
});

test('the nearest meeting wins', () => {
    const alert = agendaAlert(agenda([inMinutes(4, { title: 'Later' }), inMinutes(1)]), NOW);
    assert.equal(alert.level, 'chime');
    assert.ok(alert.key.endsWith('|Standup'));
});

test('0 turns a window off, and a server with no alerts asked for none', () => {
    assert.equal(agendaAlert(agenda([inMinutes(3)], { soon_min: 0, chime_min: 1 }), NOW), null);
    assert.equal(agendaAlert(agenda([inMinutes(1)], { soon_min: 5, chime_min: 0 }), NOW).level,
                 'soon');
    const old = { accounts: 1, events: [inMinutes(1)], failed: [] };
    assert.equal(agendaAlert(old, NOW), null);
});

test('the volume is clamped and defaulted', () => {
    assert.equal(agendaAlert(agenda([inMinutes(1)], { chime_min: 1, chime_volume: 7 }), NOW).volume, 1);
    assert.equal(agendaAlert(agenda([inMinutes(1)], { chime_min: 1 }), NOW).volume, 0.4);
});

test('the row inside the window gets the bell, and the one outside keeps the clock', () => {
    const card = agendaRows(agenda([inMinutes(3), inMinutes(40, { title: 'Later' })]), NOW, 'en');
    assert.equal(card.rows[0].icon, 'bell');
    assert.equal(card.rows[0].soon, true);
    assert.equal(card.rows[1].icon, 'clock');
    assert.equal(card.rows[1].soon, false);
});

test('agendaFields says soon for the plain theme', () => {
    assert.equal(agendaFields(agenda([inMinutes(3)]), NOW, 'en').soon, true);
    assert.equal(agendaFields(agenda([inMinutes(30)]), NOW, 'en').soon, false);
});

test('garbage never throws', () => {
    for (const bad of [null, undefined, 'x', { alerts: 'x' }, { alerts: ALERTS, events: 'x' }]) {
        assert.equal(agendaAlert(bad, NOW), null);
    }
    assert.equal(agendaAlert(agenda([inMinutes(1)]), new Date('nope')), null);
});

// Not an alert, but new in the same wave: the humidity under the range.
const { relativeHumidity } = require('../js/format.js');

test('relative humidity is a whole percent or nothing', () => {
    assert.equal(relativeHumidity({ humidity: 62 }), 62);
    assert.equal(relativeHumidity({ humidity: 61.6 }), 62);
    assert.equal(relativeHumidity({ humidity: 140 }), 100);
    assert.equal(relativeHumidity({}), null);
    assert.equal(relativeHumidity(null), null);
});
