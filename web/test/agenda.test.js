'use strict';

// T9.1: which meeting the AGENDA card shows, and how long until it starts.
// Everything here is a pure function of the payload and the phone's clock,
// which is the whole reason the countdown is computed on the phone at all
// (ADR 0017): the server sends instants, never "in 25 min".
//
// Local-time cases are built with `new Date(y, m, d, h, min)`, so they hold in
// whatever zone the suite runs in. The DST cases cannot be written that way --
// a DST boundary is a property of a zone -- so they run in a child process
// with TZ pinned, which is also how they stay true on a CI box in UTC.

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const { nextEvent, untilText, agendaFields, LANGUAGES } = require('../js/format.js');

// An RFC 3339 instant for a *local* wall-clock time, with the local offset,
// which is what a provider sends once the server has normalised it.
function at(y, mo, d, h, mi) {
    const date = new Date(y, mo - 1, d, h, mi);
    const off = -date.getTimezoneOffset();
    const sign = off >= 0 ? '+' : '-';
    const abs = Math.abs(off);
    const pad = (n) => String(n).padStart(2, '0');
    return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

function timed(start, end, source = 'google/personal', title = 'Standup') {
    return { start, end, allDay: false, source, title };
}

const NOW = new Date(2026, 8, 29, 13, 35); // Tue 29 Sep 2026, 13:35 local

test('the soonest future event is the next one', () => {
    const events = [
        timed(at(2026, 9, 29, 16, 0), at(2026, 9, 29, 16, 30), 'microsoft/work', 'Review'),
        timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30)),
    ];
    const next = nextEvent(events, NOW);
    assert.equal(next.title, 'Standup');
    assert.equal(next.inProgress, false);
});

test('an event in progress wins over the next one and says so', () => {
    const events = [
        timed(at(2026, 9, 29, 13, 45), at(2026, 9, 29, 14, 0), 'google/personal', 'Next'),
        timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 0), 'microsoft/work', 'Running'),
    ];
    const next = nextEvent(events, NOW);
    assert.equal(next.title, 'Running');
    assert.equal(next.inProgress, true);
});

test('an event that has ended is gone, and end is exclusive', () => {
    const ended = timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 13, 35));
    assert.equal(nextEvent([ended], NOW), null);
});

test('a timed event later today beats an all-day event covering today', () => {
    const events = [
        { start: '2026-09-29', end: '2026-09-30', allDay: true, source: 'google/personal', title: 'Holiday' },
        timed(at(2026, 9, 29, 17, 0), at(2026, 9, 29, 18, 0)),
    ];
    assert.equal(nextEvent(events, NOW).title, 'Standup');
});

test('an all-day event shows once no timed event is left today', () => {
    const events = [
        { start: '2026-09-29', end: '2026-09-30', allDay: true, source: 'google/personal', title: 'Holiday' },
        timed(at(2026, 9, 30, 9, 0), at(2026, 9, 30, 9, 30)),
    ];
    const next = nextEvent(events, NOW);
    assert.equal(next.title, 'Holiday');
    assert.equal(next.allDay, true);
});

test('an all-day date is local midnight, not UTC midnight', () => {
    // new Date('2026-09-30') is UTC midnight -- 21:00 on the 29th in Brazil --
    // and would put tomorrow's all-day event on today's card.
    const tomorrow = { start: '2026-09-30', end: '2026-10-01', allDay: true, source: 's', title: 'T' };
    const f = agendaFields({ accounts: 1, events: [tomorrow], failed: [] },
                           new Date(2026, 8, 29, 22, 0), 'en');
    assert.equal(f.when, 'tomorrow');
});

test('two events in the same minute always come out in the same order', () => {
    const a = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0), 'microsoft/work', 'B');
    const b = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0), 'google/personal', 'A');
    assert.equal(nextEvent([a, b], NOW).source, 'google/personal');
    assert.equal(nextEvent([b, a], NOW).source, 'google/personal');
});

test('garbage costs its own row and nothing else', () => {
    assert.equal(nextEvent(null, NOW), null);
    assert.equal(nextEvent('nope', NOW), null);
    assert.equal(nextEvent([{ start: 'tomorrow' }], NOW), null);
    const good = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30));
    const next = nextEvent([null, 42, { start: '2026-09-29T14:00' }, { allDay: true, start: '2026-02-31' }, good], NOW);
    assert.equal(next.title, 'Standup');
});

test('an instant without an offset is refused rather than guessed', () => {
    assert.equal(nextEvent([timed('2026-09-29T14:00:00', '2026-09-29T15:00:00')], NOW), null);
});

test('untilText counts minutes up, never down to zero', () => {
    const start = new Date(2026, 8, 29, 14, 0);
    assert.equal(untilText(start, new Date(2026, 8, 29, 13, 57, 30), 'en'), 'in 3 min');
    assert.equal(untilText(start, new Date(2026, 8, 29, 13, 59, 59), 'en'), 'in 1 min');
    assert.equal(untilText(start, new Date(2026, 8, 29, 13, 35), 'pt-BR'), 'em 25 min');
});

test('untilText says now at and after the start', () => {
    const start = new Date(2026, 8, 29, 14, 0);
    assert.equal(untilText(start, start, 'en'), 'now');
    assert.equal(untilText(start, new Date(2026, 8, 29, 14, 20), 'pt-BR'), 'agora');
});

test('untilText gives hours and minutes later today', () => {
    assert.equal(untilText(new Date(2026, 8, 29, 14, 45), NOW, 'en'), 'in 1 h 10');
    assert.equal(untilText(new Date(2026, 8, 29, 15, 35), NOW, 'en'), 'in 2 h');
    assert.equal(untilText(new Date(2026, 8, 29, 14, 40), NOW, 'pt-BR'), 'em 1 h 05');
});

test('untilText stays in minutes across midnight, then says tomorrow', () => {
    const late = new Date(2026, 8, 29, 23, 50);
    assert.equal(untilText(new Date(2026, 8, 30, 0, 10), late, 'en'), 'in 20 min');
    assert.equal(untilText(new Date(2026, 8, 30, 9, 0), late, 'en'), 'tomorrow 09:00');
    assert.equal(untilText(new Date(2026, 8, 30, 9, 0), late, 'pt-BR'), 'amanhã 09:00');
});

test('untilText names the weekday beyond tomorrow, and the date beyond a week', () => {
    assert.equal(untilText(new Date(2026, 9, 1, 9, 0), NOW, 'en'), 'Thu 09:00');
    assert.equal(untilText(new Date(2026, 9, 1, 9, 0), NOW, 'pt-BR'), 'qui 09:00');
    assert.equal(untilText(new Date(2026, 9, 8, 9, 0), NOW, 'en'), 'Thu 08 09:00');
});

test('untilText is empty rather than wrong for a bad date', () => {
    assert.equal(untilText(new Date('nope'), NOW, 'en'), '');
    assert.equal(untilText(null, NOW, 'en'), '');
});

// A child process, because a DST boundary belongs to a zone and the suite
// must not depend on the zone of the machine it runs on.
function inZone(tz, body) {
    const format = path.join(__dirname, '..', 'js', 'format.js');
    const code = `const f = require(${JSON.stringify(format)});\n${body}`;
    return execFileSync(process.execPath, ['-e', code], {
        env: Object.assign({}, process.env, { TZ: tz }),
        encoding: 'utf8',
    }).trim();
}

test('tomorrow is a calendar day across a DST change, not 24 hours', () => {
    // America/New_York leaves DST at 02:00 on Sunday 1 Nov 2026, so that day
    // is 25 hours long. 23:30 on the Saturday to 00:30 on the Sunday is one
    // midnight apart; dividing milliseconds by a day would call a 09:00
    // Sunday meeting, 34.5 hours out, "Mon".
    const out = inZone('America/New_York', `
        const now = new Date(2026, 9, 31, 23, 30);
        console.log(f.untilText(new Date(2026, 10, 1, 9, 0), now, 'en'));
        console.log(f.untilText(new Date(2026, 10, 2, 9, 0), now, 'en'));
    `);
    assert.deepEqual(out.split('\n'), ['tomorrow 09:00', 'Mon 09:00']);
});

test('minutes across a DST change are real minutes', () => {
    // 01:50 EDT to 01:10 EST on the same Sunday is 20 minutes of real time,
    // though the wall clock reads 40 minutes *earlier*. A countdown built on
    // wall-clock fields would say something negative, or "now".
    const out = inZone('America/New_York', `
        const now = new Date('2026-11-01T01:50:00-04:00');
        console.log(f.untilText(new Date('2026-11-01T01:10:00-05:00'), now, 'en'));
    `);
    assert.equal(out, 'in 20 min');
});

test('agendaFields is null with no card to draw', () => {
    assert.equal(agendaFields(undefined, NOW, 'en'), null);
    assert.equal(agendaFields({ accounts: 0, events: [], failed: [] }, NOW, 'en'), null);
    assert.equal(agendaFields('x', NOW, 'en'), null);
});

test('agendaFields draws the countdown and the title', () => {
    const f = agendaFields({
        accounts: 1,
        events: [timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30))],
        failed: [],
    }, NOW, 'pt-BR');
    assert.deepEqual(f, { title: 'Standup', when: 'em 25 min', until: null, inProgress: false, failed: null });
});

test('agendaFields uses the generic word when the PC withheld the title', () => {
    const f = agendaFields({
        accounts: 1,
        events: [{ start: at(2026, 9, 29, 14, 0), end: at(2026, 9, 29, 14, 30), allDay: false, source: 's' }],
        failed: [],
    }, NOW, 'en');
    assert.equal(f.title, 'Meeting');
});

test('agendaFields says until when in progress, and all day for an all-day event', () => {
    const running = agendaFields({
        accounts: 1,
        events: [timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 30))],
    }, NOW, 'pt-BR');
    assert.equal(running.when, 'agora · até 14:30');
    assert.equal(running.until, 'até 14:30');
    assert.equal(running.inProgress, true);
    const allDay = agendaFields({
        accounts: 1,
        events: [{ start: '2026-09-29', end: '2026-09-30', allDay: true, source: 's', title: 'Feriado' }],
    }, NOW, 'pt-BR');
    assert.equal(allDay.when, 'o dia todo');
});

test('a failed account is named and the other one still draws', () => {
    const f = agendaFields({
        accounts: 2,
        events: [timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30))],
        failed: ['microsoft/work', 7],
    }, NOW, 'en');
    assert.equal(f.title, 'Standup');
    assert.equal(f.failed, 'microsoft/work: reconnect');
});

test('no event at all still draws a card that says so', () => {
    const f = agendaFields({ accounts: 1, events: [], failed: [] }, NOW, 'en');
    assert.deepEqual(f, { title: null, when: 'nothing ahead', until: null, inProgress: false, failed: null });
});

test('every language has every agenda word', () => {
    const reference = LANGUAGES['pt-BR'].agenda;
    for (const [tag, table] of Object.entries(LANGUAGES)) {
        assert.deepEqual(Object.keys(table.agenda).sort(), Object.keys(reference).sort(), tag);
        assert.equal(table.agenda.weekdays.length, 7, tag);
    }
});
