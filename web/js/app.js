const clockEl = document.getElementById('clock');
const dateEl = document.getElementById('date');

function updateClock() {
    const now = new Date();

    // Format time: HH:mm:ss
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    clockEl.textContent = `${hours}:${minutes}:${seconds}`;

    // Format date: Day Month Date, Year
    const options = {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    };
    dateEl.textContent = now.toLocaleDateString(undefined, options);
}

// Initial call
updateClock();
// Update every second, while anyone can see it. The handle is kept so the
// offline state can stop it: see window.onPcState below.
let clockTimer = setInterval(updateClock, 1000);

// --- PC state --------------------------------------------------------------
// Called from native Java on every transition and only on transitions
// (MainActivity.onPcState), never from here: web/ has no network code at all
// (invariant 1, ADR 0002). In the browser it is simply never called, and the
// panel stays in its online look, which is the one worth developing against.

window.onPcState = (online) => {
    // One class on <body>; the stylesheet owns what that means. Pure black is
    // not decoration on an AMOLED - a black pixel is an off pixel - so the
    // offline look is the cheapest thing the display can show while the
    // backlight is on its way out (ADR 0005).
    document.body.classList.toggle('pc-offline', !online);

    // Nothing is visible offline, so a per-second DOM write is pure cost, and
    // it is cost paid in exactly the state the device holds a wake lock to
    // survive (ADR 0014). Stopping the timer is worth more here than it looks.
    if (online && clockTimer === null) {
        updateClock();
        clockTimer = setInterval(updateClock, 1000);
    } else if (!online && clockTimer !== null) {
        clearInterval(clockTimer);
        clockTimer = null;
    }
};

// --- Data rendering --------------------------------------------------------
// window.onData(payload) is the one entry point for quotes, fx, crypto,
// weather and battery — native in production, js/mock.js in the browser.
// Payload shape: tasks/T1.2-mock-fixtures.md. All formatting is delegated to
// format.js (loaded before this file); this just places values in the DOM.

const quotesEl = document.getElementById('quotes');
const fxEl = document.getElementById('fx');
const cryptoEl = document.getElementById('crypto');
const weatherEl = document.getElementById('weather');
const batteryEl = document.getElementById('battery');
const staleEl = document.getElementById('stale-badge');

function renderRow(label, value, currency, changePct, format = formatPrice) {
    const row = document.createElement('div');
    row.className = 'row';

    const labelEl = document.createElement('span');
    labelEl.className = 'label';
    labelEl.textContent = label;

    const priceEl = document.createElement('span');
    priceEl.className = 'price';
    priceEl.textContent = format(value, currency);

    const changeEl = document.createElement('span');
    changeEl.className = `change ${changeClass(changePct)}`;
    changeEl.textContent = formatChange(changePct);

    row.append(labelEl, priceEl, changeEl);
    return row;
}

// `format` is how FX opts out of formatPrice: a rate is not a price, and
// formatPrice's magnitude-dependent precision is wrong for one in both
// directions. See formatRate in format.js.
function renderList(container, items, labelField, valueField, currency,
                   format = formatPrice, formatLabel = (label) => label) {
    container.textContent = '';
    for (const item of items) {
        container.appendChild(
            renderRow(formatLabel(item[labelField], currency), item[valueField],
                      currency, item.changePct, format));
    }
}

function renderWeather(weather) {
    weatherEl.textContent = '';
    if (!weather) {
        return;
    }
    const line = document.createElement('div');
    line.textContent = `${weather.city}: ${weather.tempC}°C (${weather.minC}-${weather.maxC}°C) ${weatherLabel(weather.code)}`;
    weatherEl.appendChild(line);
}

function renderBattery(battery) {
    batteryEl.textContent = '';
    if (!battery) {
        return;
    }
    const line = document.createElement('div');
    const chargingSuffix = battery.charging ? ' (charging)' : '';
    line.textContent = `Battery ${battery.level}% ${battery.tempC}°C${chargingSuffix}`;
    batteryEl.appendChild(line);
}

window.onData = (payload) => {
    if (!payload) {
        return;
    }
    renderList(quotesEl, payload.quotes || [], 'symbol', 'price', 'BRL');
    renderList(fxEl, payload.fx || [], 'pair', 'rate', 'BRL', formatRate, formatPair);
    renderList(cryptoEl, payload.crypto || [], 'symbol', 'price', 'USD');
    renderWeather(payload.weather);
    renderBattery(payload.battery);
    staleEl.hidden = !payload.stale;
};
