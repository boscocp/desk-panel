// A sky this panel has no picture of.
//
// `weatherGlyph` answers 'unknown' for every WMO code outside its set, and the
// set is not the whole standard: 56, 57, 66, 67, 77, 85 and 86 are real
// open-meteo values -- freezing drizzle, freezing rain, ice grains, snow
// showers -- and `providers_openmeteo.normalise` forwards whatever code it was
// given. So this is a payload the real feed can produce on a cold morning, not
// a hypothetical.
//
// It exists because of what T6.12 did and what its review found. The condition
// used to be a line of prose under the range; removing that line moved the word
// into the glyph's accessible name, and a code with no glyph has no element to
// carry it -- so the card said `3°C 1° / 5°` about freezing rain and nothing at
// all about the freezing. The fix draws the word where the picture would have
// been, which makes the glyph slot a box that can hold text, which is a width
// this harness had never measured.
//
// The city is the long one and the temperature is negative for the same reason
// stress.js uses them: the fallback word has to fit *beside* the widest number
// the card can be asked to draw, not on its own.
//
// Everything else is deliberately ordinary. This pass is about one card.

window.onData({
    quotes: [
        { symbol: 'PETR4', price: 38.42, changePct: 1.2 },
        { symbol: 'VALE3', price: 61.75, changePct: -0.6 },
        { symbol: 'ITUB4', price: 32.10, changePct: 0 },
    ],
    fx: [
        { pair: 'USD/BRL', rate: 5.12, changePct: -0.3 },
        { pair: 'EUR/BRL', rate: 5.58, changePct: 0.4 },
    ],
    crypto: [
        { symbol: 'BTC', price: 341200, changePct: 2.8 },
        { symbol: 'ETH', price: 4210.55, changePct: -1.9 },
    ],
    // 66 is freezing rain. It has no glyph and no label in either language, so
    // both tables fall through to `unknown` -- which is the whole point: the
    // widest thing the fallback can say is "Desconhecido", twelve characters,
    // and it has to say it beside `-10°C`.
    weather: { tempC: -10, minC: -12, maxC: 42, code: 66, city: 'Sao Jose dos Campos' },
    battery: { level: 100, tempC: 42.5, charging: false },
    stale: false,
    // Carried through for the same reason stress.js carries them: without
    // these a --theme or --lang run would measure the default panel while
    // printing the name of the one that was asked for (T6.7, T6.11).
    theme: new URLSearchParams(location.search).get('theme') || undefined,
    language: new URLSearchParams(location.search).get('lang') || undefined,
});

return true;
