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

const {
    nextEvent, untilText, agendaFields, agendaRows, agendaSegments, LANGUAGES,
} = require('../js/format.js');

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


test('the soonest future event is the next one', () => {
    const events = [
        timed(at(2026, 9, 29, 16, 0), at(2026, 9, 29, 16, 30), 'microsoft/work', 'Review'),
        timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30)),
    ];
    const next = nextEvent(events, NOW);
    assert.equal(next.title, 'Standup');
    assert.equal(next.inProgress, false);
});

test('of two events in progress, the one that started last wins', () => {
    // A 09-18 focus block must not hide the 13:30 meeting that has just
    // started inside it -- that is the meeting you are late for.
    const events = [
        timed(at(2026, 9, 29, 9, 0), at(2026, 9, 29, 18, 0), 'g', 'Focus'),
        timed(at(2026, 9, 29, 13, 30), at(2026, 9, 29, 14, 0), 'm', 'Board'),
    ];
    assert.equal(nextEvent(events, NOW).title, 'Board');
    assert.equal(nextEvent(events.slice().reverse(), NOW).title, 'Board');
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
    // and would put tomorrow's all-day event on today's card. In a child
    // process in Sao Paulo, because in UTC -- which is what CI runs in -- the
    // two midnights are the same one and the bug passes.
    const out = inZone('America/Sao_Paulo', `
        const tomorrow = { start: '2026-09-30', end: '2026-10-01', allDay: true, source: 's', title: 'T' };
        console.log(f.agendaFields({ accounts: 1, events: [tomorrow], failed: [] },
                                   new Date(2026, 8, 29, 22, 0), 'en').when);
    `);
    assert.equal(out, 'tomorrow');
});

test('an all-day event that ended at today\'s midnight is gone', () => {
    // `end` is exclusive for all-day events too: yesterday's holiday ends at
    // the midnight that starts today.
    const yesterday = { start: '2026-09-28', end: '2026-09-29', allDay: true, source: 'g', title: 'Y' };
    assert.equal(nextEvent([yesterday], NOW), null);
});

test('on a later day a timed event comes before an all-day one', () => {
    // The all-day event starts at midnight, so by start alone it would win.
    const allDay = { start: '2026-09-30', end: '2026-10-01', allDay: true, source: 'g', title: 'Trip' };
    const meeting = timed(at(2026, 9, 30, 9, 0), at(2026, 9, 30, 9, 30), 'g', 'Standup');
    assert.equal(nextEvent([allDay, meeting], NOW).title, 'Standup');
});

test('near midnight a meeting within the hour beats today\'s all-day event', () => {
    // untilText calls a 00:10 meeting "in 20 min" at 23:50, so the card must
    // not put the holiday that ends at midnight above it.
    const late = new Date(2026, 8, 29, 23, 50);
    const holiday = { start: '2026-09-29', end: '2026-09-30', allDay: true, source: 'g', title: 'Feriado' };
    const soon = timed(at(2026, 9, 30, 0, 10), at(2026, 9, 30, 0, 40), 'g', 'Late call');
    const f = agendaFields({ accounts: 1, events: [holiday, soon], failed: [] }, late, 'en');
    assert.equal(f.title, 'Late call');
    assert.equal(f.when, 'in 20 min');
    // An hour and more out, it is tomorrow's meeting and today still has the
    // holiday.
    const tomorrow = timed(at(2026, 9, 30, 0, 51), at(2026, 9, 30, 1, 30), 'g', 'Later');
    assert.equal(nextEvent([holiday, tomorrow], late).title, 'Feriado');
});

test('2026-02-31 is not quietly 3 March', () => {
    // On 3 March the rolled-over date would cover today and be drawn.
    const bogus = { start: '2026-02-31', end: '2026-03-04', allDay: true, source: 'g', title: 'X' };
    assert.equal(nextEvent([bogus], new Date(2026, 2, 3, 12, 0)), null);
});

test('source decides a tie even when the titles would order it the other way', () => {
    const a = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0), 'microsoft/work', 'A');
    const b = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0), 'google/personal', 'B');
    assert.equal(nextEvent([a, b], NOW).source, 'google/personal');
});

test('the title decides a tie between two events from one source', () => {
    const a = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0), 'g', 'B');
    const b = timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0), 'g', 'A');
    assert.equal(nextEvent([a, b], NOW).title, 'A');
    assert.equal(nextEvent([b, a], NOW).title, 'A');
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
    // :59 and not :30 -- at the half minute rounding and ceiling agree, and
    // only a test they disagree on can tell them apart.
    assert.equal(untilText(start, new Date(2026, 8, 29, 13, 57, 59), 'en'), 'in 3 min');
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
    // In a zone that is not UTC, because in UTC the local calendar and the
    // UTC one are the same and a day computed from the wrong one passes.
    const out = inZone('America/Sao_Paulo', `
        const late = new Date(2026, 8, 29, 23, 50);
        console.log(f.untilText(new Date(2026, 8, 30, 0, 10), late, 'en'));
        console.log(f.untilText(new Date(2026, 8, 30, 9, 0), late, 'en'));
        console.log(f.untilText(new Date(2026, 8, 30, 9, 0), late, 'pt-BR'));
        // 22:00 in Sao Paulo is 01:00 UTC the next day: a UTC calendar
        // would call a 23:30 meeting "tomorrow".
        console.log(f.untilText(new Date(2026, 8, 29, 23, 30), new Date(2026, 8, 29, 22, 0), 'en'));
    `);
    assert.deepEqual(out.split('\n'), ['in 20 min', 'tomorrow 09:00', 'amanhã 09:00', 'in 1 h 30']);
});

test('untilText names the weekday beyond tomorrow, and the date beyond a week', () => {
    assert.equal(untilText(new Date(2026, 9, 1, 9, 0), NOW, 'en'), 'Thu 09:00');
    assert.equal(untilText(new Date(2026, 9, 1, 9, 0), NOW, 'pt-BR'), 'qui 09:00');
    // Six days out is still this week; seven is next week's Tuesday, and
    // needs the date to not be read as today.
    assert.equal(untilText(new Date(2026, 9, 5, 9, 0), NOW, 'en'), 'Mon 09:00');
    assert.equal(untilText(new Date(2026, 9, 6, 9, 0), NOW, 'en'), 'Tue 06 09:00');
    assert.equal(untilText(new Date(2026, 9, 8, 9, 0), NOW, 'en'), 'Thu 08 09:00');
});

test('untilText is empty rather than wrong for a bad date', () => {
    assert.equal(untilText(new Date('nope'), NOW, 'en'), '');
    assert.equal(untilText(null, NOW, 'en'), '');
});

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

test('a blank title is no title', () => {
    const f = agendaFields({
        accounts: 1,
        events: [timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30), 's', '   ')],
    }, NOW, 'en');
    assert.equal(f.title, 'Meeting');
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

test('an event in progress that ends on another day says which', () => {
    const conference = timed(at(2026, 9, 28, 10, 0), at(2026, 9, 30, 10, 0), 'g', 'Conference');
    const f = agendaFields({ accounts: 1, events: [conference] }, NOW, 'pt-BR');
    assert.equal(f.until, 'até amanhã 10:00');
    assert.equal(f.when, 'agora · até amanhã 10:00');
    const trip = timed(at(2026, 9, 28, 10, 0), at(2026, 10, 1, 18, 0), 'g', 'Trip');
    assert.equal(agendaFields({ accounts: 1, events: [trip] }, NOW, 'en').until, 'until Thu 18:00');
});

test('a failed account is named and the other one still draws', () => {
    const f = agendaFields({
        accounts: 2,
        events: [timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 14, 30))],
        failed: [{ source: 'microsoft/work', reason: 'reconnect' }],
    }, NOW, 'en');
    assert.equal(f.title, 'Standup');
    assert.equal(f.failed, 'microsoft/work: reconnect');
});

test('only a refused login asks to reconnect; an outage says unavailable', () => {
    const f = agendaFields({
        accounts: 3,
        events: [],
        failed: [
            { source: 'google/work', reason: 'unavailable' },
            { source: 'microsoft/work', reason: 'reconnect' },
            { source: 'google/personal', reason: 'unavailable' },
        ],
    }, NOW, 'pt-BR');
    assert.equal(f.failed,
        'microsoft/work: reconectar · google/work, google/personal: indisponível');
});

test('a bare string in failed is read as reconnect, and junk is skipped', () => {
    const f = agendaFields({
        accounts: 2, events: [], failed: ['microsoft/work', 7, null, { reason: 'unavailable' }],
    }, NOW, 'en');
    assert.equal(f.failed, 'microsoft/work: reconnect');
});

test('with an account failing and no event, the card does not claim nothing is ahead', () => {
    const f = agendaFields({
        accounts: 2, events: [], failed: [{ source: 'google/personal', reason: 'unavailable' }],
    }, NOW, 'en');
    assert.equal(f.when, '');
    assert.equal(f.failed, 'google/personal: unavailable');
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


// agendaRows: the neon card's two rows (the quest tracker).

function card(events, failed = []) {
    return { accounts: 1, events, failed };
}

test('agendaRows: a meeting in progress carries its end, what is left and how far through it is', () => {
    // 13:35, in a 13:00-14:00 meeting: 35 of 60 minutes gone.
    const out = agendaRows(card([timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 0))]), NOW, 'pt-BR');
    assert.equal(out.rows.length, 1);
    const [row] = out.rows;
    assert.equal(row.icon, 'live');
    assert.equal(row.live, true);
    assert.equal(row.when, 'até 14:00');
    assert.equal(row.aside, '25 min');
    assert.ok(Math.abs(row.progress - 35 / 60) < 1e-9);
    assert.equal(out.none, null);
});

test('agendaRows: up to three events, best first', () => {
    const out = agendaRows(card([
        timed(at(2026, 9, 29, 17, 0), at(2026, 9, 29, 17, 30), 'google/personal', '1:1'),
        timed(at(2026, 9, 29, 13, 50), at(2026, 9, 29, 14, 20)),
        timed(at(2026, 9, 30, 9, 0), at(2026, 9, 30, 9, 30), 'google/personal', 'third'),
    ]), NOW, 'pt-BR');
    assert.deepEqual(out.rows.map((r) => r.title), ['Standup', '1:1', 'third']);
    assert.equal(out.rows[2].when, 'amanhã 09:00');
    // First row: the countdown, with the clock time beside it.
    assert.equal(out.rows[0].when, 'em 15 min');
    assert.equal(out.rows[0].aside, '13:50');
    assert.equal(out.rows[0].progress, null);
    // Second row, three hours away today: the time, not "em 3 h 25".
    assert.equal(out.rows[1].when, '17:00');
    assert.equal(out.rows[1].aside, null);
    assert.equal(out.rows[1].icon, 'clock');
});

test('agendaRows: tomorrow keeps its day, and an all-day event is a calendar', () => {
    const out = agendaRows(card([
        timed(at(2026, 9, 30, 9, 0), at(2026, 9, 30, 9, 30)),
        { start: '2026-09-29', end: '2026-09-30', allDay: true, source: 'google/personal', title: 'Feriado' },
    ]), NOW, 'en');
    assert.deepEqual(out.rows.map((r) => [r.icon, r.when]),
        [['calendar', 'all day'], ['clock', 'tomorrow 09:00']]);
});

test('agendaRows: a failure is a line under the rows, not instead of them', () => {
    const out = agendaRows(card([
        timed(at(2026, 9, 29, 14, 0), at(2026, 9, 29, 15, 0)),
        timed(at(2026, 9, 29, 16, 0), at(2026, 9, 29, 17, 0)),
        timed(at(2026, 9, 29, 18, 0), at(2026, 9, 29, 19, 0)),
    ], [{ source: 'microsoft/work', reason: 'reconnect' }]), NOW, 'pt-BR');
    // All three: how many fit beside the failure line is the theme's call.
    assert.equal(out.rows.length, 3);
    assert.equal(out.failed, 'microsoft/work: reconectar');
});

test('agendaRows: nothing ahead says so, unless an account failed', () => {
    assert.equal(agendaRows(card([]), NOW, 'pt-BR').none, 'nada à vista');
    assert.equal(agendaRows(card([], ['google/personal']), NOW, 'pt-BR').none, null);
    assert.equal(agendaRows({ accounts: 0, events: [] }, NOW, 'pt-BR'), null);
    assert.equal(agendaRows(undefined, NOW, 'pt-BR'), null);
});

test('agendaRows: the last seconds of a meeting are 1 min, and over an hour is "1 h 10"', () => {
    const almost = new Date(2026, 8, 29, 13, 59, 30);
    const one = agendaRows(card([timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 0))]), almost, 'pt-BR');
    assert.equal(one.rows[0].aside, '1 min');
    const long = agendaRows(card([timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 45))]), NOW, 'pt-BR');
    assert.equal(long.rows[0].aside, '1 h 10');
});

test('agendaRows: a first row tomorrow says its time once', () => {
    const out = agendaRows(card([timed(at(2026, 9, 30, 9, 0), at(2026, 9, 30, 9, 30))]), NOW, 'en');
    assert.equal(out.rows[0].when, 'tomorrow 09:00');
    assert.equal(out.rows[0].aside, null);
});

test('agendaRows: a countdown past midnight keeps the clock time beside it', () => {
    // 23:50, a meeting at 00:10: "em 20 min" with 00:10 beside it.
    const late = new Date(2026, 8, 29, 23, 50);
    const out = agendaRows(card([timed(at(2026, 9, 30, 0, 10), at(2026, 9, 30, 0, 40))]), late, 'pt-BR');
    assert.equal(out.rows[0].when, 'em 20 min');
    assert.equal(out.rows[0].aside, '00:10');
});

test('agendaRows: the second row switches to a clock time at exactly one hour', () => {
    const first = timed(at(2026, 9, 29, 13, 40), at(2026, 9, 29, 13, 45), 'a', 'first');
    const hour = agendaRows(card([first, timed(at(2026, 9, 29, 14, 35), at(2026, 9, 29, 15, 0), 'b', 'x')]),
        NOW, 'pt-BR');
    assert.equal(hour.rows[1].when, '14:35');
    const under = agendaRows(card([first, timed(at(2026, 9, 29, 14, 34), at(2026, 9, 29, 15, 0), 'b', 'x')]),
        NOW, 'pt-BR');
    assert.equal(under.rows[1].when, 'em 59 min');
});

test('agendaRows: time left rounds up in the middle of a minute', () => {
    const t = new Date(2026, 8, 29, 13, 35, 20);
    const out = agendaRows(card([timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 0))]), t, 'pt-BR');
    assert.equal(out.rows[0].aside, '25 min');
});

test('agendaRows: a meeting in progress that ends tomorrow says so, with no time left beside it', () => {
    // "20 h 25" beside "até amanhã 10:00" cut off the time on the card.
    const out = agendaRows(card([timed(at(2026, 9, 29, 11, 35), at(2026, 9, 30, 10, 0))]), NOW, 'pt-BR');
    assert.equal(out.rows[0].when, 'até amanhã 10:00');
    assert.equal(out.rows[0].aside, null);
    assert.equal(out.rows[0].live, true);
});

test('agendaRows: two meetings at once are both live', () => {
    const out = agendaRows(card([
        timed(at(2026, 9, 29, 13, 0), at(2026, 9, 29, 14, 0), 'a', 'one'),
        timed(at(2026, 9, 29, 13, 30), at(2026, 9, 29, 13, 50), 'b', 'two'),
    ]), NOW, 'pt-BR');
    // The one that started last comes first, as in nextEvent.
    assert.deepEqual(out.rows.map((r) => [r.title, r.live, r.when]),
        [['two', true, 'até 13:50'], ['one', true, 'até 14:00']]);
});

test('agendaSegments: floor, so a full bar means the meeting is over', () => {
    assert.equal(agendaSegments(0.35, 10), 3);
    assert.equal(agendaSegments(57 / 60, 10), 9);
    assert.equal(agendaSegments(0.999, 10), 9);
    assert.equal(agendaSegments(1, 10), 10);
    assert.equal(agendaSegments(0, 10), 0);
    assert.equal(agendaSegments(null, 10), 0);
    assert.equal(agendaSegments(1.5, 10), 10);
});

test('agendaRows: never more than three, however many the server sent', () => {
    const events = [];
    for (let h = 14; h < 20; h += 1) {
        events.push(timed(at(2026, 9, 29, h, 0), at(2026, 9, 29, h, 30), 'a', `m${h}`));
    }
    assert.deepEqual(agendaRows(card(events), NOW, 'pt-BR').rows.map((r) => r.title),
        ['m14', 'm15', 'm16']);
});
