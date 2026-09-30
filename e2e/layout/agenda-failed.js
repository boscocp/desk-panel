// agenda.js's three events with a two-line failure line under them.
//
// The case the neon card answers by drawing two events, both compact: three
// rows and a failure are ~42px taller than the card. That cap lives in
// theme.js, which no node test loads, so this pass is the only thing that
// notices if it goes -- the failure line would be drawn off the bottom of the
// screen.

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
            accounts: 3,
            // Three, the most the card draws, with long titles on the two
            // behind it: the tallest the card can be -- chip, bar, a stacked
            // second row and a compact third.
            events: [{
                start: new window.Date(now.getTime() - 2 * 3600000).toISOString(),
                end: end.toISOString(),
                allDay: false, source: 'microsoft/work',
                title: 'Offsite de planejamento com todas as equipes de produto',
            }, {
                start: new window.Date(now.getTime() + 40 * 60000).toISOString(),
                end: new window.Date(now.getTime() + 70 * 60000).toISOString(),
                allDay: false, source: 'google/personal',
                title: 'Exame de sangue no laboratório do centro',
            }, {
                start: new window.Date(now.getTime() + 90 * 60000).toISOString(),
                end: new window.Date(now.getTime() + 120 * 60000).toISOString(),
                allDay: false, source: 'google/personal',
                title: 'Revisão trimestral do orçamento da casa',
            }],
            failed: [{ source: 'microsoft/work', reason: 'reconnect' },
                     { source: 'google/work', reason: 'unavailable' }],
        };
    })(),
});

return true;
