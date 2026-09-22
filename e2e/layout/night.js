// A clear sky after dark, which is the payload the whole of T6.13 came from.
//
// On 2026-09-21 at 21:20 the panel drew a **sun** for `Predominantemente
// limpo`. The server had never asked open-meteo for `is_day`, so the page could
// not know; the endpoint answered `{"weather_code": 1, "is_day": 0}` for Sao
// Paulo at 21:15 that evening, measured before the task was written.
//
// So this pass is about two things that only exist at night:
//
//   - the sky's glyph is not a sun. `weatherGlyph(1, false)` is `stars`, and
//     stars rather than a moon because the moon has its own permanent place on
//     this card -- drawing it twice would be the card saying one thing in two
//     sizes.
//   - the moon is drawn at a phase whose shape is not a disc and not a
//     semicircle. `first-quarter` at 50% is the one phase whose terminator is a
//     straight line, which is the arc this geometry is most likely to get
//     wrong: the ellipse's horizontal radius is r * |1 - 2k| and at k = 0.5
//     that is exactly zero.
//
// Everything else is the ordinary served payload. This pass is about one card.
window.onData({
    quotes: [
        { symbol: 'PETR4', price: 38.42, changePct: 1.2 },
        { symbol: 'VALE3', price: 61.75, changePct: -0.6 },
        { symbol: 'ITUB4', price: 32.10, changePct: 0 },
    ],
    fx: [
        { pair: 'USD-BRL', rate: 5.12, changePct: -0.3 },
        { pair: 'EUR-BRL', rate: 5.58, changePct: 0.4 },
    ],
    crypto: [
        { symbol: 'BTC', price: 341200.0, changePct: 2.8 },
        { symbol: 'ETH', price: 4210.55, changePct: -1.9 },
    ],
    weather: {
        tempC: 22.2, minC: 15.0, maxC: 26.0, code: 1, city: 'Sao Paulo',
        isDay: false,
        precipProb: 7,
        moon: { phase: 'first-quarter', illum: 50, source: 'usno' },
    },
    battery: { level: 87, tempC: 31.0, charging: true },
    stale: false,
});
