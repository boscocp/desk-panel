window.onPcState = (online) => {
    console.log("PC State:", online);
};

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
// Update every second
setInterval(updateClock, 1000);

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

function renderRow(label, value, currency, changePct) {
    const row = document.createElement('div');
    row.className = 'row';

    const labelEl = document.createElement('span');
    labelEl.className = 'label';
    labelEl.textContent = label;

    const priceEl = document.createElement('span');
    priceEl.className = 'price';
    priceEl.textContent = formatPrice(value, currency);

    const changeEl = document.createElement('span');
    changeEl.className = `change ${changeClass(changePct)}`;
    changeEl.textContent = formatChange(changePct);

    row.append(labelEl, priceEl, changeEl);
    return row;
}

function renderList(container, items, labelField, valueField, currency) {
    container.textContent = '';
    for (const item of items) {
        container.appendChild(renderRow(item[labelField], item[valueField], currency, item.changePct));
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
    renderList(fxEl, payload.fx || [], 'pair', 'rate', 'BRL');
    renderList(cryptoEl, payload.crypto || [], 'symbol', 'price', 'USD');
    renderWeather(payload.weather);
    renderBattery(payload.battery);
    staleEl.hidden = !payload.stale;
};
