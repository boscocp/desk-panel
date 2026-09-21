// More rows than any card can show, which is the case T6.6 exists for.
//
// The panel is exactly one screen and every card clips, so before T6.6 a ninth
// ticker arriving from server config was not truncated and not marked -- it was
// simply absent, and nothing on the panel said so. The fix is that a card with
// hidden rows walks slowly through them, and the only machine-checkable
// statement of it is this: with this payload on screen, the three list cards
// must report `data-scroll`. A card that overflows without it is back to
// eating rows in silence, and check_layout.py fails the pass.
//
// Nine, eight and eight rather than "a few more than fit": the counts have to
// overflow the neon theme's three tall cards AND the plain theme's four short
// columns, whose rows are two lines each. One fixture, both themes, and the
// margin is deliberate so a font that resolves differently on another machine
// cannot turn this pass into a no-op.
//
// The symbols are plausible B3, FX and crypto rows rather than filler: a card
// scrolling through PETR4, VALE3 and ITUB4 is what this looks like on the desk,
// and the widest label in the repo (SHIBAINU-VERYLONGNAME, from mock.js) is
// kept so the ellipsis is still under test while the card is moving.

function quote(symbol, price, changePct) {
    return { symbol: symbol, price: price, changePct: changePct };
}

window.onData({
    quotes: [
        quote('PETR4', 38.42, 1.2),
        quote('VALE3', 61.75, -0.6),
        quote('ITUB4', 32.10, 0),
        quote('BBAS3', 27.88, 0.9),
        quote('WEGE3', 52.31, -1.4),
        quote('ABEV3', 12.07, 0.2),
        quote('TAEE11', 36.44, -0.3),
        quote('B3SA3', 11.95, 1.8),
        quote('MGLU3', 9.42, -2.7),
    ],
    fx: [
        { pair: 'USD/BRL', rate: 5.12, changePct: -0.3 },
        { pair: 'EUR/BRL', rate: 5.58, changePct: 0.4 },
        { pair: 'GBP/BRL', rate: 6.49, changePct: 0.1 },
        { pair: 'JPY/BRL', rate: 0.034, changePct: -0.8 },
        { pair: 'ARS/BRL', rate: 0.0053, changePct: 0 },
        { pair: 'CNY/BRL', rate: 0.767, changePct: 0.6 },
        { pair: 'CHF/BRL', rate: 6.02, changePct: -0.2 },
        { pair: 'AUD/BRL', rate: 3.41, changePct: 1.1 },
    ],
    crypto: [
        quote('BTC', 341200, 2.8),
        quote('ETH', 4210.55, -1.9),
        quote('SOL', 188.31, 3.4),
        quote('XRP', 2.41, 0),
        quote('ADA', 0.884, -0.7),
        quote('DOGE', 0.2117, 5.2),
        quote('SHIBAINU-VERYLONGNAME', 0.00081, -4.5),
        quote('LINK', 21.66, 1.3),
    ],
    weather: { tempC: 23, minC: 18, maxC: 27, code: 2, city: 'Sao Paulo' },
    battery: { level: 87, tempC: 31, charging: true },
    stale: false,
    // Carried through for the same reason stress.js carries it: without it a
    // --theme run would switch the panel back to the default and measure the
    // wrong one while reporting the right name (T6.7).
    theme: new URLSearchParams(location.search).get('theme') || undefined,
    // And the language, for the same reason: without it a --lang run would
    // put the panel back into pt-BR the moment this fixture landed, and
    // report the right tag while measuring the wrong words (T6.11).
    language: new URLSearchParams(location.search).get('lang') || undefined,
});

return true;
