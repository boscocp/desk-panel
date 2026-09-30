// Mock data feed for browser-only development: Chrome, no APK, no phone, no
// server. Feeds window.onData() the exact payload shape production sends, so
// the panel can be built and reviewed with nothing else running.
//
// Loaded by index.html like every other script, and gated by the guard at the
// top of the IIFE below rather than by a conditional loader in the markup:
// the rest of the page is deferred, and a script injected from an inline
// <script> cannot be placed in that ordered list, so it could run before
// window.onData existed. The guard is what keeps it inert in the APK — it has
// always shipped inside assets/, since build.gradle.kts points assets.srcDirs
// straight at web/.
//
// The payload shape is a contract between three places: this file, the
// server's /quotes and /weather responses, and the Android DataPoller.
// Each quote/fx/crypto row also carries `history`, an array of recent values
// oldest first, which the panel draws as a sparkline, and the payload carries
// `theme`, the name of a directory in web/themes/ (T6.7).
// Changing a key here means changing it in both other places too. See
// tasks/T1.2-mock-fixtures.md for the full shape.

(function () {
    'use strict';

    // The APK serves the panel from https://appassets.androidplatform.net/,
    // never from file:, so this is the whole of the test for "am I in a
    // browser?". __nativeBridge is checked as well because it is the name a
    // future JavaScript interface would take, and a mock feed fighting a real
    // one is a confusing thing to debug.
    if (location.protocol !== 'file:' || typeof window.__nativeBridge !== 'undefined') {
        return;
    }

    // Develop a theme in a browser: open web/index.html?theme=plain. The name
    // rides the payload in production too — it comes from the server's config
    // (T3.12) — so this is the same path, fed from the query string instead of
    // from the PC. e2e/layout/check_layout.py --theme uses it to measure a
    // theme other than the default.
    const THEME = new URLSearchParams(location.search).get('theme') || undefined;
    // Draw the CLOSED label beside the B3 title: open web/index.html?b3=closed.
    // Without it the market shuts every fourth tick -- four, not three, so a
    // closed market is not always drawn beside the flat quote the third tick
    // makes.
    const B3_CLOSED = new URLSearchParams(location.search).get('b3') === 'closed';

    // Develop in the other language: open web/index.html?lang=en. Same path
    // as production, where the tag comes from the PC's config (T6.11), fed
    // from the query string instead of from the server. Absent unless asked
    // for, so the browser shows what the device shows -- an unset language is
    // what a config that never mentions one sends, and the panel falls back
    // to pt-BR.
    const LANGUAGE = new URLSearchParams(location.search).get('lang') || undefined;

    // Which shortcut buttons exist, as the server's `actions` key would say
    // (T8.2 step 4). Both, by default, so a theme's buttons are visible in a
    // browser without a phone -- and `?actions=` renders none, which is the
    // state a panel whose owner enabled nothing is in and is the easier one to
    // forget to draw correctly.
    const ACTIONS = (() => {
        const asked = new URLSearchParams(location.search).get('actions');
        if (asked === null) {
            return ['mute-audio', 'mute-mic'];
        }
        return asked ? asked.split(',') : [];
    })();

    // The next meetings (T9.1), as the server's `agenda` would say. Instants
    // fixed at page load rather than rebuilt per tick, so the countdown in a
    // browser moves the way it does on the desk: one minute a minute, from the
    // phone's clock, while the payload keeps arriving unchanged. One meeting
    // 25 minutes out, one an hour after it with a title long enough to have to
    // ellipsise, and an all-day event behind both. `?agenda=off` sends a PC
    // with no calendar connected, which leaves the card reserved -- the state
    // a theme is most likely to forget to draw. `?agenda=live` starts the
    // first meeting 35 minutes ago, for the chip and the progress bar.
    const AGENDA = (() => {
        const asked = new URLSearchParams(location.search).get('agenda');
        if (asked === 'off') {
            return { accounts: 0, events: [], failed: [] };
        }
        const now = Date.now();
        const minutes = (n) => new Date(now + n * 60000).toISOString();
        const today = new Date();
        const day = (offset) => {
            const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset);
            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        };
        return {
            accounts: 2,
            events: [
                { start: minutes(asked === 'live' ? -35 : 25),
                  end: minutes(asked === 'live' ? 25 : 55), allDay: false,
                  source: 'google/personal', title: 'Standup' },
                { start: minutes(85), end: minutes(145), allDay: false,
                  source: 'microsoft/work',
                  title: 'Quarterly planning with the platform and data teams' },
                { start: day(0), end: day(1), allDay: true, source: 'google/personal',
                  title: 'Aniversário' },
            ],
            failed: [],
        };
    })();

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

    // isDay and moon are what the server sends since T6.13. They are in the
    // served payload rather than only in a stress fixture because the moon is
    // *permanent* on the card: a check that never saw it would be measuring a
    // panel the device does not have.
    //
    // 84% waxing gibbous is the real answer for 2026-09-22T00:27Z, derived
    // from the USNO's own table -- the evening the task was asked for.
    const BASE_WEATHER = {
        tempC: 23, minC: 18, maxC: 27, code: 2, city: 'Sao Paulo',
        isDay: true,
        // The day's chance of rain (T6.15), as a daily max like the
        // temperatures beside it. 98 is what the live endpoint answered for
        // Sao Paulo on 2026-09-22.
        precipProb: 98,
        moon: { phase: 'waxing-gibbous', illum: 84, source: 'usno' },
    };
    const BASE_BATTERY = { level: 87, tempC: 31, charging: true };
    const NIGHT = { start: '22:00', end: '07:00' };

    let tick = 0;

    // A plausible series for the sparkline, built once per base value rather
    // than jittered per tick: a chart that redrew its whole history every
    // three seconds would flicker, and real daily closes do not move.
    function series(base, drift, points) {
        const out = [];
        let value = base * (1 - drift);
        for (let i = 0; i < points; i += 1) {
            value += (base * drift * 2) / points + (Math.random() * 2 - 1) * base * 0.004;
            out.push(Number(value.toFixed(8)));
        }
        return out;
    }

    const HISTORY = new Map();
    function historyFor(key, base) {
        if (!HISTORY.has(key)) {
            // A deliberate mix of directions, so the up, down and flat colour
            // paths are all on screen at once in a browser.
            const drift = { PETR4: 0.06, VALE3: -0.04, ITUB4: 0.0,
                            'USD/BRL': -0.02, 'EUR/BRL': 0.03,
                            BTC: 0.09 }[key] ?? 0.05;
            HISTORY.set(key, series(base, drift, 30));
        }
        return HISTORY.get(key);
    }

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

    function jitterEntries(list, pricePct, priceKey, labelKey) {
        return list.map((item) => ({
            ...item,
            [priceKey]: round(jitterPct(item[priceKey], pricePct)),
            changePct: Number(jitter(item.changePct, 0.4).toFixed(1)),
            history: historyFor(item[labelKey], item[priceKey]),
        }));
    }

    function buildPayload() {
        tick += 1;

        const quotes = jitterEntries(BASE_QUOTES, 0.01, 'price', 'symbol');
        // Every third tick: a flat quote, so the zero-change path renders too.
        if (tick % 3 === 0) {
            quotes[2].changePct = 0;
        }

        return {
            quotes,
            fx: jitterEntries(BASE_FX, 0.005, 'rate', 'pair'),
            crypto: jitterEntries(BASE_CRYPTO, 0.02, 'price', 'symbol'),
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
            language: LANGUAGE,
            // Absent unless asked for, so the browser shows what the device
            // shows: an unset `theme` is what a config that never mentions one
            // sends, and the panel falls back to neon.
            theme: THEME,
            actions: ACTIONS,
            // The market shut, now and then or for good: see B3_CLOSED.
            b3Open: B3_CLOSED ? false : tick % 4 !== 0,
            // Every seventh tick one account fails, so the failure line is
            // drawn in a browser too -- the same argument `stale` makes above.
            // A failed account contributes no events, exactly as on the PC, so
            // its meeting leaves the card for that tick.
            agenda: tick % 7 === 0 && AGENDA.accounts
                ? {
                    ...AGENDA,
                    events: AGENDA.events.filter((e) => e.source !== 'microsoft/work'),
                    failed: [{ source: 'microsoft/work', reason: 'reconnect' }],
                }
                : AGENDA,
        };
    }

    // The bridge MainActivity installs, stubbed so the buttons can be built
    // and reviewed in a browser. It answers like the real one -- true means
    // "dispatched", and the outcome arrives separately at onActionResult --
    // because a stub that reported success synchronously would let a theme be
    // written against a shape production does not have.
    //
    // Every third press fails, deliberately. The failure state is the one a
    // theme is most likely to draw wrongly and least likely to see by
    // accident, and a mock that always succeeds ships it untested (the same
    // argument `stale` above is made with).
    let presses = 0;
    window.__actions = {
        invoke: (id) => {
            const ok = ++presses % 3 !== 0;
            console.log('mock: action ' + id + ' -> ' + (ok ? 'ok' : 'err'));
            setTimeout(() => window.onActionResult(id, ok), 250);
            return true;
        },
    };

    window.onData(buildPayload());
    setInterval(() => window.onData(buildPayload()), 3000);
})();
