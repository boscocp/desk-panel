// The plain theme. It exists to prove the boundary is real: it renders the
// same payload with different markup, in a different order, with no shared
// stylesheet and no shared element tree -- and core does not change by a line
// to allow it (T6.7's manual check).
//
// Deliberately not a second design. It is what a contributor's first theme
// looks like: one heading and a list per section, everything in the flow, no
// sparklines, no glow, no absolute positioning. If this renders and the panel
// still works, a theme really is a directory.
//
// The differences from neon are the point, so they are listed rather than left
// to be noticed:
//   - the row is label, change, value -- the change sits *before* the number
//     it describes, which is exactly the kind of thing T6.7 says a theme must
//     be able to say and could not before,
//   - headings are real elements, not ::before content,
//   - the battery is a line in the flow, not a corner absolute,
//   - the weather is three lines rather than one sentence,
//   - one row of four equal columns, not a sidebar and a card block.

(function () {
    'use strict';

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

    // A section is a heading plus a body the renderers refill. Two elements
    // rather than one because the heading is markup here, which is half of
    // what this theme is demonstrating.
    //
    // Three elements now: the body is the window and the scroller inside it is
    // what moves when a column holds more rows than it can show (T6.6). The
    // arrangement is the same one the neon theme uses -- it has to be, because
    // the rule it obeys is "a card must not eat a row in silence", and that is
    // a rule about the panel and not about a look.
    function column(id, title) {
        const section = el('section', id, 'col');
        const heading = el('h2', null, 'col-title');
        heading.textContent = title;
        const body = el('div', null, 'col-body');
        const scroller = el('div', null, 'scroller');
        body.appendChild(scroller);
        section.append(heading, body);
        return { section, body, scroller };
    }

    function mount(root) {
        root.textContent = '';

        const clock = el('div', 'clock');
        const date = el('div', 'date');
        const stale = el('div', 'stale-badge');
        stale.textContent = 'STALE';
        stale.hidden = true;

        const header = el('header', null, 'header');
        header.append(clock, date, stale);

        // Reserved for the shortcut buttons, as in neon: the space exists
        // before the buttons do.
        const shortcuts = el('div', 'shortcuts');

        const quotes = column('quotes', 'B3');
        const fx = column('fx', 'FX');
        const crypto = column('crypto', 'Crypto');
        const weather = column('weather', 'Weather');

        const grid = el('div', null, 'grid');
        grid.append(quotes.section, fx.section, crypto.section, weather.section);

        const battery = el('section', 'battery');

        root.append(header, grid, battery, shortcuts);
        els = {
            root, clock, date, stale, battery,
            quotes, fx, crypto,
            // The scroller, not the bundle: the weather column is not a list
            // and nothing calls applyScroll on it. It has one anyway because
            // column() builds every section the same way, and a fourth shape of
            // section to save one empty div is a worse trade. It clips like any
            // other card if a forecast ever outgrows it, exactly as it did
            // before T6.6.
            weather: weather.scroller,
        };
    }

    function ensure(root) {
        if (!els || els.root !== root || !root.contains(els.clock)) {
            mount(root);
        }
    }

    // Label, change, value. The order is the whole demonstration: in neon the
    // change is last, and nothing outside a theme decides that any more.
    function row(label, change, value) {
        const node = el('div', null, 'row');
        const labelEl = el('span', null, 'label');
        labelEl.textContent = label;
        const changeEl = el('span', null, `change ${changeClass(change)}`);
        changeEl.textContent = formatChange(change);
        const valueEl = el('span', null, 'value');
        valueEl.textContent = value;
        node.append(labelEl, changeEl, valueEl);
        return node;
    }

    function fill(list, items, labelField, valueField, currency, format, formatLabel) {
        list.scroller.textContent = '';
        for (const item of items) {
            const label = formatLabel ? formatLabel(item[labelField], currency)
                                      : item[labelField];
            list.scroller.appendChild(
                row(label, item.changePct, format(item[valueField], currency)));
        }
        applyScroll(list, items.length);
    }

    // The same measurement the neon theme makes, and deliberately not shared
    // code: the arithmetic is shared -- it is scrollPlan, in format.js -- and
    // the measuring is not, because this theme's rows are two lines tall and
    // neon's are one. A helper that measured both would have to be told what a
    // row is by each of them, which is the same amount of code with an extra
    // seam in it.
    function applyScroll(list, rowCount) {
        const available = list.body.clientHeight;
        const content = list.scroller.scrollHeight;
        const rowHeight = rowCount > 0 ? content / rowCount : 0;
        const visibleRows = rowHeight > 0 ? available / rowHeight : rowCount;
        const style = getComputedStyle(list.section);
        const plan = scrollPlan(rowCount, visibleRows,
                                parseFloat(style.getPropertyValue('--scroll-seconds-per-row')));
        // The second half is the twitch guard the neon theme's copy of this
        // explains at length: integer box metrics at dpr 2.75 can invent a
        // hidden row that is one pixel tall, and a card that moved for it would
        // twitch on the device and pass every check here.
        if (!plan || !worthScrolling(content - available)) {
            list.section.removeAttribute('data-scroll');
            list.scroller.style.removeProperty('--scroll-distance');
            list.scroller.style.removeProperty('--scroll-seconds');
            return;
        }
        // The list drawn twice and moved by exactly one copy (T6.9), which is
        // the same seam the neon theme makes and for the same reason. The
        // pitch is measured off the clone rather than computed from
        // scrollHeight: this theme's rows are two lines tall with a rule
        // between them and none after the last, so a copy inside a pair is
        // one rule taller than a copy on its own.
        const rows = Array.from(list.scroller.children);
        for (const row of rows) {
            list.scroller.appendChild(row.cloneNode(true));
        }
        const pitch = rows.length
            ? list.scroller.children[rows.length].offsetTop - rows[0].offsetTop
            : 0;
        list.scroller.style.setProperty('--scroll-distance', `${Math.round(pitch)}px`);
        list.scroller.style.setProperty('--scroll-seconds', `${plan.seconds}s`);
        list.section.setAttribute('data-scroll', '');
    }

    // Four lines, because a narrow column and one long sentence do not agree
    // -- "Sao Jose dos Campos: -10°C (-10-42°C) Thunderstorm, heavy hail" is a
    // real payload (e2e/layout/stress.js).
    //
    // The range comes from formatRange now (T6.8), not from two formatTemp
    // calls joined here. This theme had already reached for a ` / ` separator
    // on its own, which is most of the argument for the function existing: the
    // hyphen was ambiguous below zero in neon and would have been ambiguous
    // here too, and a rule that each theme has to rediscover is a rule in the
    // wrong file. No glyph: this theme is undesigned on purpose, and the label
    // is the whole of what it has to say.
    function renderWeather(weather) {
        els.weather.textContent = '';
        if (!weather) {
            return;
        }
        const city = el('div', null, 'w-city');
        city.textContent = weather.city;
        const temp = el('div', null, 'w-temp');
        temp.textContent = `${formatTemp(weather.tempC)}°C`;
        const range = el('div', null, 'w-range');
        range.textContent = formatRange(weather.minC, weather.maxC);
        const cond = el('div', null, 'w-cond');
        cond.textContent = weatherLabel(weather.code);
        els.weather.append(city, temp, range, cond);
    }

    function renderBattery(battery) {
        els.battery.textContent = '';
        const text = formatBattery(battery);
        if (!text) {
            return;
        }
        const line = el('div', null, tempClass(battery.tempC));
        line.textContent = text;
        els.battery.appendChild(line);
    }

    function render(payload, root) {
        ensure(root);
        if (!payload) {
            return;
        }
        fill(els.quotes, payload.quotes || [], 'symbol', 'price', 'BRL', formatPrice);
        fill(els.fx, payload.fx || [], 'pair', 'rate', 'BRL', formatRate, formatPair);
        fill(els.crypto, payload.crypto || [], 'symbol', 'price', 'USD', formatPrice);
        renderWeather(payload.weather);
        renderBattery(payload.battery);
        els.stale.hidden = !payload.stale;
    }

    function tick(now, root) {
        ensure(root);
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        const seconds = String(now.getSeconds()).padStart(2, '0');
        // HH:MM:SS, like every theme: native reads this string by id to prove
        // the page rendered (docs/THEMING.md).
        els.clock.textContent = `${hours}:${minutes}:${seconds}`;
        els.date.textContent = now.toLocaleDateString(undefined, {
            weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
        });
    }

    window.DeskPanel.defineTheme('plain', { render, tick });
})();
