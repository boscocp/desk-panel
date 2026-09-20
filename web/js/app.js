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

// --- Thermal state ---------------------------------------------------------
// Called from native Java (MainActivity.onThermal) when the device crosses a
// thermal threshold, and on every page load so a reloaded panel is not left
// painting into a phone that is still too hot (T5.5, ADR 0012).
//
// The window's brightness is already at zero by the time this arrives; this is
// the black render that goes with it, for a display whose floor is a dim
// backlight rather than none.

window.onThermal = (tooHot) => {
    document.body.classList.toggle('too-hot', !!tooHot);
};

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

// The sparkline's drawing box, in SVG user units. The element is sized in CSS
// and the viewBox scales to it, so these are a shape rather than a size.
const SPARK_W = 56;
const SPARK_H = 16;

// An inline <svg>, built through createElementNS because SVG lives in its own
// namespace -- createElement('svg') produces an HTML element of that name that
// renders as nothing at all, silently.
// Returns null when there is no series, and the caller appends nothing.
// An empty <svg> still reserves its flex basis, which is how a B3 row with no
// history -- brapi serves none without a paid range -- rendered TAEE11 as
// "TAEE…": the label gave up the width, and it gave it to a picture of
// nothing.
function renderSparkline(history, changePct) {
    const d = sparklinePath(history, SPARK_W, SPARK_H);
    if (!d) {
        return null;
    }
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', `spark ${changeClass(changePct)}`);
    svg.setAttribute('viewBox', `0 0 ${SPARK_W} ${SPARK_H}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    // Decoration: the row already states the number and the change in text,
    // so a screen reader gains nothing from the path and is better off
    // skipping it.
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
    return svg;
}

function renderRow(label, value, currency, changePct, format = formatPrice, history = []) {
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

    // Between the price and the change, so the eye reads name, number, shape,
    // direction -- and so the two coloured things sit together. append()
    // ignores nothing, so a row with no series simply has no gap for one.
    const spark = renderSparkline(history, changePct);
    row.append(labelEl, priceEl, ...(spark ? [spark] : []), changeEl);
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
                      currency, item.changePct, format, item.history));
    }
}

function renderWeather(weather) {
    weatherEl.textContent = '';
    if (!weather) {
        return;
    }
    const line = document.createElement('div');
    line.textContent = `${weather.city}: ${formatTemp(weather.tempC)}°C `
        + `(${formatTemp(weather.minC)}-${formatTemp(weather.maxC)}°C) `
        + `${weatherLabel(weather.code)}`;
    weatherEl.appendChild(line);
}

// The one diagnostic on a panel of content, so it is a corner line rather than
// a card (T5.4 step 3): no title, no border, and nothing until there is
// something to say. An empty string leaves the corner genuinely empty, which is
// what the panel should look like before the first battery broadcast arrives.
function renderBattery(battery) {
    batteryEl.textContent = '';
    const text = formatBattery(battery);
    if (!text) {
        return;
    }
    const line = document.createElement('div');
    // The whole line takes the colour, not just the number: at 20px in a
    // corner, a single re-coloured word is easy to miss and the temperature is
    // right there to explain it.
    //
    // 'normal' is set as a class rather than left empty so the three bands read
    // as three states in the DOM; the stylesheet gives it nothing.
    line.className = tempClass(battery.tempC);
    line.textContent = text;
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
