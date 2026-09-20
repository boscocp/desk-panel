// The neon theme: the panel's default look, and everything T6.7 took out of
// js/app.js. The move was byte-for-byte where it could be -- renderRow,
// renderSparkline, renderList, renderWeather and renderBattery are the same
// functions, and the skeleton below is web/index.html's old <body> -- so a
// difference on screen after this task is a defect and not a redesign.
//
// What a theme is allowed to assume, and nothing more (docs/THEMING.md):
//   - it is handed a root element and owns everything inside it,
//   - js/format.js is loaded first, so its formatters are globals here,
//   - the blackout is core's, so there is nothing to do about being offline.
//
// What it owes:
//   - an element with id="clock" holding HH:MM:SS, which MainActivity reads
//     out of the DOM to log panel=rendered (T2.2, ADR 0009),
//   - no `visibility: visible` anywhere, which would defeat the blackout.

(function () {
    'use strict';

    // The sparkline's drawing box, in SVG user units. The element is sized in
    // CSS and the viewBox scales to it, so these are a shape rather than a
    // size.
    const SPARK_W = 56;
    const SPARK_H = 16;

    // The skeleton's elements, cached between renders. Null until mount().
    let els = null;

    function el(tag, id, className) {
        const node = document.createElement(tag);
        if (id) {
            node.id = id;
        }
        if (className) {
            node.className = className;
        }
        return node;
    }

    // Built once, then updated in place. Rebuilding the whole panel on every
    // payload would take the clock with it -- and the clock is the one element
    // outside this theme's gift, because native reads it by id.
    function mount(root) {
        root.textContent = '';

        const clock = el('div', 'clock');
        const date = el('div', 'date');
        const clockContainer = el('div', 'clock-container');
        clockContainer.append(clock, date);

        // Reserved for the shortcut buttons: empty on purpose, so that adding
        // them later fills a space that already exists instead of forcing the
        // panel to be laid out again (T6.1 step, and the v2 feature T3.7
        // reserved the server route for).
        const shortcuts = el('div', 'shortcuts');

        const sidebar = el('div', 'sidebar');
        sidebar.append(clockContainer, shortcuts);

        const quotes = el('section', 'quotes', 'card-list');
        const fx = el('section', 'fx', 'card-list');
        const crypto = el('section', 'crypto', 'card-list');
        const weather = el('section', 'weather', 'card');
        // Not a .card: the battery is a diagnostic, and T5.4 demotes it to a
        // line in the corner rather than a fifth box with a title. The class
        // is what carried the border, the padding and the DEVICE label.
        const battery = el('section', 'battery');
        const stale = el('div', 'stale-badge');
        stale.textContent = 'STALE';
        stale.hidden = true;

        const panel = el('div', 'panel');
        panel.append(quotes, fx, crypto, weather, battery, stale);

        root.append(sidebar, panel);
        els = { root, clock, date, quotes, fx, crypto, weather, battery, stale };
    }

    // Cheap, and called on every render and tick. `root.contains` rather than
    // a flag, because host.js empties the root when the theme changes: a flag
    // would say "mounted" about a DOM that no longer holds any of it.
    function ensure(root) {
        if (!els || els.root !== root || !root.contains(els.clock)) {
            mount(root);
        }
    }

    // An inline <svg>, built through createElementNS because SVG lives in its
    // own namespace -- createElement('svg') produces an HTML element of that
    // name that renders as nothing at all, silently.
    // Returns null when there is no series, and the caller appends nothing.
    // An empty <svg> still reserves its flex basis, which is how a B3 row with
    // no history -- brapi serves none without a paid range -- rendered TAEE11
    // as "TAEE…": the label gave up the width, and it gave it to a picture of
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
        // Decoration: the row already states the number and the change in
        // text, so a screen reader gains nothing from the path and is better
        // off skipping it.
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        svg.appendChild(path);
        return svg;
    }

    function renderRow(label, value, currency, changePct, format = formatPrice, history = []) {
        const row = el('div', null, 'row');

        const labelEl = el('span', null, 'label');
        labelEl.textContent = label;

        const priceEl = el('span', null, 'price');
        priceEl.textContent = format(value, currency);

        const changeEl = el('span', null, `change ${changeClass(changePct)}`);
        changeEl.textContent = formatChange(changePct);

        // Between the price and the change, so the eye reads name, number,
        // shape, direction -- and so the two coloured things sit together.
        // append() ignores nothing, so a row with no series simply has no gap
        // for one.
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
        els.weather.textContent = '';
        if (!weather) {
            return;
        }
        const line = el('div');
        line.textContent = `${weather.city}: ${formatTemp(weather.tempC)}°C `
            + `(${formatTemp(weather.minC)}-${formatTemp(weather.maxC)}°C) `
            + `${weatherLabel(weather.code)}`;
        els.weather.appendChild(line);
    }

    // The one diagnostic on a panel of content, so it is a corner line rather
    // than a card (T5.4 step 3): no title, no border, and nothing until there
    // is something to say. An empty string leaves the corner genuinely empty,
    // which is what the panel should look like before the first battery
    // broadcast arrives.
    function renderBattery(battery) {
        els.battery.textContent = '';
        const text = formatBattery(battery);
        if (!text) {
            return;
        }
        const line = el('div');
        // The whole line takes the colour, not just the number: at 20px in a
        // corner, a single re-coloured word is easy to miss and the
        // temperature is right there to explain it.
        //
        // 'normal' is set as a class rather than left empty so the three bands
        // read as three states in the DOM; the stylesheet gives it nothing.
        line.className = tempClass(battery.tempC);
        line.textContent = text;
        els.battery.appendChild(line);
    }

    // `payload` is null before the first word from the PC: the skeleton is
    // built and the cards are empty, which is what the panel looked like in
    // that state before T6.7 too.
    function render(payload, root) {
        ensure(root);
        if (!payload) {
            return;
        }
        renderList(els.quotes, payload.quotes || [], 'symbol', 'price', 'BRL');
        renderList(els.fx, payload.fx || [], 'pair', 'rate', 'BRL', formatRate, formatPair);
        renderList(els.crypto, payload.crypto || [], 'symbol', 'price', 'USD');
        renderWeather(payload.weather);
        renderBattery(payload.battery);
        els.stale.hidden = !payload.stale;
    }

    function tick(now, root) {
        ensure(root);

        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        // HH:MM:SS exactly: MainActivity logs this string as evidence the page
        // rendered, and e2e/layout/measure.js asserts its shape.
        els.clock.textContent = `${hours}:${minutes}:${seconds}`;

        els.date.textContent = now.toLocaleDateString(undefined, {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }

    window.DeskPanel.defineTheme('neon', { render, tick });
})();
