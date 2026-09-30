// A meeting in progress that ends on another day (T9.1).
//
// The one AGENDA line stress.js cannot carry, because stress.js spends the
// first row on the widest countdown. In progress, neon's head line draws the
// AGORA chip beside "até amanhã 10:00" and, because the meeting does not end
// today, no time-left beside that -- which is what keeps the time on screen.
// This pass is what says it fits.
//
// Everything else is deliberately ordinary. This pass is about one card.

window.onData({
    quotes: [
        { symbol: 'PETR4', price: 38.42, changePct: 1.2 },
        { symbol: 'VALE3', price: 61.75, changePct: -0.6 },
    ],
    fx: [{ pair: 'USD/BRL', rate: 5.12, changePct: -0.3 }],
    crypto: [{ symbol: 'BTC', price: 341200, changePct: 2.8 }],
    weather: {
        tempC: 24, minC: 18, maxC: 28, code: 2, city: 'Sao Paulo', isDay: true,
        precipProb: 10, moon: { phase: 'full', illum: 100, source: 'usno' },
    },
    battery: { level: 80, tempC: 31, charging: true },
    stale: false,
    theme: new URLSearchParams(location.search).get('theme') || undefined,
    language: new URLSearchParams(location.search).get('lang') || undefined,
    agenda: (() => {
        // `window.Date`: this runs in Marionette's sandbox, whose own Date is
        // the harness's clock rather than the page's pinned one (stress.js).
        const now = new window.Date();
        const end = new window.Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 10, 0);
        return {
            accounts: 1,
            events: [{
                start: new window.Date(now.getTime() - 2 * 3600000).toISOString(),
                end: end.toISOString(),
                allDay: false, source: 'microsoft/work',
                title: 'Offsite de planejamento com todas as equipes de produto',
            }],
            failed: [],
        };
    })(),
});

return true;
