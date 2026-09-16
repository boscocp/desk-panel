// Mock data feed for browser-only development: Chrome, no APK, no phone, no
// server. Feeds window.onData() the exact payload shape production sends, so
// the panel can be built and reviewed with nothing else running.
//
// Loaded by index.html only behind a guard that keeps it out of the APK —
// see the inline script at the bottom of index.html. Never reference this
// file from anywhere that also runs inside the WebView.
//
// The payload shape is a contract between three places: this file, the
// server's /quotes and /weather responses, and the Android DataPoller.
// Changing a key here means changing it in both other places too. See
// tasks/T1.2-mock-fixtures.md for the full shape.

(function () {
    'use strict';

    const BASE_QUOTES = [
        { symbol: 'PETR4', price: 38.42, changePct: 1.2 },
        { symbol: 'VALE3', price: 61.75, changePct: -0.6 },
        { symbol: 'ITUB4', price: 32.10, changePct: 0.3 },
    ];

    const BASE_FX = [
        { pair: 'USD/BRL', rate: 5.12, changePct: -0.3 },
        { pair: 'EUR/BRL', rate: 5.58, changePct: 0.4 },
    ];

    const BASE_CRYPTO = [
        { symbol: 'BTC', price: 341200, changePct: 2.8 },
        // Deliberately long, to prove layout survives a symbol that does not
        // fit the usual 3-5 character ticker.
        { symbol: 'SHIBAINU-VERYLONGNAME', price: 0.00081, changePct: -4.5 },
    ];

    const BASE_WEATHER = { tempC: 23, minC: 18, maxC: 27, code: 2, city: 'Sao Paulo' };
    const BASE_BATTERY = { level: 87, tempC: 31, charging: true };
    const NIGHT = { start: '22:00', end: '07:00' };

    let tick = 0;

    // Absolute jitter for small, roughly-fixed-range values (changePct).
    function jitter(value, spread) {
        return value + (Math.random() * 2 - 1) * spread;
    }

    // Relative jitter for prices: BTC (~341200) and the long-name coin below
    // (~0.0008) sit in the same list, so a fixed absolute spread would either
    // do nothing to BTC or send the small one negative. A percentage works
    // for both.
    function jitterPct(value, pct) {
        return value * (1 + (Math.random() * 2 - 1) * pct);
    }

    function round(value) {
        // Sub-1 prices (e.g. the long-name crypto above) need more than two
        // decimals or every tick jitters it to the same rounded value.
        const decimals = Math.abs(value) < 1 ? 6 : 2;
        return Number(value.toFixed(decimals));
    }

    function jitterEntries(list, pricePct, priceKey) {
        return list.map((item) => ({
            ...item,
            [priceKey]: round(jitterPct(item[priceKey], pricePct)),
            changePct: Number(jitter(item.changePct, 0.4).toFixed(1)),
        }));
    }

    function buildPayload() {
        tick += 1;

        const quotes = jitterEntries(BASE_QUOTES, 0.01, 'price');
        // Every third tick: a flat quote, so the zero-change path renders too.
        if (tick % 3 === 0) {
            quotes[2].changePct = 0;
        }

        return {
            quotes,
            fx: jitterEntries(BASE_FX, 0.005, 'rate'),
            crypto: jitterEntries(BASE_CRYPTO, 0.02, 'price'),
            weather: {
                ...BASE_WEATHER,
                tempC: Math.round(jitter(BASE_WEATHER.tempC, 2)),
            },
            battery: {
                ...BASE_BATTERY,
                level: Math.max(0, Math.min(100, Math.round(jitter(BASE_BATTERY.level, 1)))),
            },
            // Every fifth tick: upstream looked stale, last-good values held.
            // Must actually happen here, or the degraded path ships untested.
            stale: tick % 5 === 0,
            night: NIGHT,
        };
    }

    window.onData(buildPayload());
    setInterval(() => window.onData(buildPayload()), 3000);
})();
