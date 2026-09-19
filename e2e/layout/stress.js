// The widest case the panel can legitimately be asked to show.
//
// A typical tick never breaks a layout. This one exists because every value in
// it has, or plausibly could, come out of the real feed:
//
//   - the longest label in format.js's WMO table ("Thunderstorm, heavy hail")
//   - a long city name, since the city is server config and not a rebuild
//   - a negative temperature with a wide min-max, which is the longest weather
//     line that can be built
//   - a six-figure crypto price and a sub-1 crypto price in the same card, so
//     the price column has to hold both
//   - a symbol far longer than a 3-5 character ticker, to prove the label
//     ellipsis is load-bearing rather than decorative
//   - a zero change, which formats without a sign and takes the flat colour
//   - a negative change, the widest of the three
//   - stale: true, which paints the STALE badge over the top-right corner
//
// The first five come from web/js/mock.js, which put them there for the same
// reason; the rest cannot be got from a served tick.
//
// Also forces the clock to 23:59:59 (the widest time) and the date to pt-BR,
// which is what the phone actually renders and is far longer than en-US.

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
        { symbol: 'SHIBAINU-VERYLONGNAME', price: 0.00081, changePct: -4.5 },
    ],
    weather: { tempC: -10, minC: -12, maxC: 42, code: 99, city: 'Sao Jose dos Campos' },
    // charging: false on purpose. This is the widest battery line the code can
    // produce -- the 'unplugged' word is only in the discharging variant -- and
    // with charging: true it was never measured, which is how T5.4 shipped a
    // corner line that grew out of its column and covered the CRYPTO card.
    battery: { level: 100, tempC: 42.5, charging: false },
    stale: true,
});

document.getElementById('clock').textContent = '23:59:59';
document.getElementById('date').textContent = new Date().toLocaleDateString('pt-BR', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
});

return true;
