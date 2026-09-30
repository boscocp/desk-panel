'use strict';

// The page's half of the payload description (T10.1).
//
// `web/js/mock.js` is what a contributor with a browser and nothing else
// develops against, and until now it was the copy of the payload shape that
// nothing asserted anything about: it could drift from what the PC sends and
// the only symptom would be a panel that works in Chrome and not on the desk.
//
// `server/tests/test_payload_contract.py` generates the description from the
// server's own assembly. This file holds mock.js to it.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { LANGUAGES, shortcutsFor } = require('../js/format.js');

const FIXTURES = path.join(__dirname, '..', '..', 'server', 'tests', 'fixtures');

function description(name) {
    const file = path.join(FIXTURES, name);
    assert.ok(fs.existsSync(file),
        `${file} is missing — generate it with DESK_PANEL_WRITE_FIXTURES=1 `
        + 'python -m unittest server.tests.test_payload_contract');
    return JSON.parse(fs.readFileSync(file, 'utf8'));
}

// mock.js is an IIFE that guards on `location.protocol` and then calls
// `window.onData`. Loading it means being the browser it expects: the guard is
// the whole reason the same file is inert inside the APK, so a test that
// bypassed it would be testing a file the panel does not have.
function payloadFromMock() {
    const captured = [];
    const realSetInterval = global.setInterval;
    global.window = { onData: (payload) => captured.push(payload) };
    global.location = { protocol: 'file:', search: '' };
    // The feed repeats every three seconds in a browser. Here the first
    // payload is the whole point, and a live interval would hold node open.
    global.setInterval = () => 0;
    try {
        delete require.cache[require.resolve('../js/mock.js')];
        require('../js/mock.js');
    } finally {
        global.setInterval = realSetInterval;
        delete global.window;
        delete global.location;
    }
    assert.equal(captured.length, 1, 'mock.js fed the page nothing');
    return captured[0];
}

test('mock.js feeds the page exactly what the panel receives', () => {
    const sent = description('payload.json').quotes;

    // What the phone adds to the server's body before the page sees it:
    // `weather` is the other endpoint, folded in by DataPayload.merge, and
    // `battery` is the device's own reading, folded in by withBattery. Both
    // are the page's contract even though neither rides /quotes.
    const expected = new Set([...Object.keys(sent), 'weather', 'battery']);
    const actual = new Set(Object.keys(payloadFromMock()));

    const missing = [...expected].filter((key) => !actual.has(key));
    const extra = [...actual].filter((key) => !expected.has(key));
    assert.deepEqual(missing, [],
        'the PC sends these and mock.js does not, so a browser-only contributor '
        + 'develops against a panel that is missing them');
    assert.deepEqual(extra, [],
        'mock.js feeds these and nothing on the desk does, so they can be built '
        + 'against and will never arrive');
});

test('the page has a word for every action the server can offer', () => {
    // The third copy of the action list. `actions.CATALOGUE` is Python,
    // `Actions.ALLOWED` is Java, and this is the one that decides whether a
    // button is drawn at all: shortcutsFor drops any id it has no word for,
    // which is correct behaviour and silent. An action added on the PC and
    // not here is a button that never appears, in one language only if the
    // translation is half done.
    // `volume` is in the catalogue and is not a button (T8.4): it is the
    // bar beside them, with a word of its own.
    const catalogue = description('action_ids.json').catalogue;
    const buttons = catalogue.filter((id) => id !== 'volume');
    for (const language of Object.keys(LANGUAGES)) {
        const drawn = shortcutsFor(catalogue, language).map((button) => button.id);
        assert.deepEqual(drawn, buttons,
            `${language} has no word for one of the server's actions`);
        assert.ok(LANGUAGES[language].volume, `${language} has no word for the volume bar`);
    }
});
