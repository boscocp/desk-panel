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

        // Each list is three elements, not one, and the nesting is what makes
        // T6.6's scroll possible at all:
        //
        //   section.card-list   the card, and the clip -- unchanged
        //     div.card-body     the window: as tall as the card allows
        //       div.scroller    as tall as its rows, and the thing that moves
        //
        // The scroller is built here, once, and refilled by renderList on
        // every payload. That is the whole answer to "the refresh must not
        // restart the scroll": a CSS animation belongs to an element, and
        // replacing an element's children does not disturb it. Put the
        // animation on the section and refill the section, and the card would
        // reset to the top every 60s and never reach the rows it exists to
        // reveal.
        const lists = {};
        for (const section of [quotes, fx, crypto]) {
            const body = el('div', null, 'card-body');
            const scroller = el('div', null, 'scroller');
            body.appendChild(scroller);
            section.appendChild(body);
            lists[section.id] = { section, body, scroller };
        }
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
        els = { root, clock, date, lists, weather, battery, stale };
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
    function renderList(list, items, labelField, valueField, currency,
                        format = formatPrice, formatLabel = (label) => label) {
        list.scroller.textContent = '';
        for (const item of items) {
            list.scroller.appendChild(
                renderRow(formatLabel(item[labelField], currency), item[valueField],
                          currency, item.changePct, format, item.history));
        }
        applyScroll(list, items.length);
    }

    // The theme's half of T6.6: measure, ask format.js whether that is an
    // overflow, and either turn the scroll on or take it away.
    //
    // The measuring is here because only a theme knows what a row looks like,
    // and it is done in pixels and converted to rows rather than the other way
    // around: rows carry a 1px border between them and the last one does not,
    // so a row height derived from the CSS would be wrong by a pixel per row
    // and the card would scroll by a row it did not have.
    //
    // The travel is the leftover pixels, not a whole number of rows. A pass
    // that ends on a row boundary leaves the bottom row half out of the card
    // at the one moment the card exists to show it.
    function applyScroll(list, rowCount) {
        const available = list.body.clientHeight;
        const content = list.scroller.scrollHeight;
        // An average, which is exactly right here: every row in a card is the
        // same height, and the average absorbs the borders that are only
        // between them.
        const rowHeight = rowCount > 0 ? content / rowCount : 0;
        const visibleRows = rowHeight > 0 ? available / rowHeight : rowCount;

        const style = getComputedStyle(list.section);
        const plan = scrollPlan(rowCount, visibleRows,
                                cssNumber(style, '--scroll-seconds-per-row'),
                                cssNumber(style, '--scroll-moving-fraction'));

        // Two questions, and the second is not the first one restated.
        // scrollPlan counts rows and says whether any are hidden;
        // worthScrolling looks at the pixels those rows came out to and says
        // whether they are worth moving for. On this machine the second never
        // fires -- the review of T6.6 is where it came from, and the case is
        // the device: clientHeight and scrollHeight are integers, the phone
        // lays out at dpr 2.75, and a card whose rows exactly fill it can
        // report 102px of content in a 101px window. One hidden row, one pixel
        // of travel, a compositor layer held for the life of the panel, and a
        // card twitching in the corner of someone's eye every seventeen
        // seconds -- with every check in e2e/layout passing, because a pixel of
        // overflow is a real overflow as far as a measurement can tell.
        if (!plan || !worthScrolling(content - available)) {
            // Both halves matter. The attribute is what the stylesheet keys the
            // animation off, so a card that stopped overflowing stops moving;
            // the property is removed with it so nothing is left pointing at a
            // distance that no longer exists.
            list.section.removeAttribute('data-scroll');
            list.scroller.style.removeProperty('--scroll-distance');
            list.scroller.style.removeProperty('--scroll-seconds');
            return;
        }

        // Written on every refresh, and on a refresh that changed no rows these
        // are the same two strings as last time -- so the declaration does not
        // change, and a CSS animation whose declaration does not change is not
        // restarted. That, plus a scroller element mount() never replaces, is
        // the whole of step 4.
        list.scroller.style.setProperty('--scroll-distance',
                                        `${Math.round(content - available)}px`);
        list.scroller.style.setProperty('--scroll-seconds', `${plan.seconds}s`);
        // On the section rather than on the scroller, because it says something
        // about the card and not about the moving box: e2e/layout/measure.js
        // reads it to tell a deliberate scroll from a card silently eating its
        // own rows, which is the fault this task is fixing (docs/THEMING.md).
        list.section.setAttribute('data-scroll', '');
    }

    // A custom property read back as a number, or NaN when the theme did not
    // set one -- which is the value scrollPlan treats as "use your default",
    // so a theme that says nothing still scrolls sensibly.
    function cssNumber(style, name) {
        return parseFloat(style.getPropertyValue(name));
    }

    // The condition, drawn. One path per name in format.js's closed set, in a
    // 24-unit box, stroked in the current colour so the glyph takes the card's
    // ink and never needs a palette of its own.
    //
    // Inline, and not a webfont: the WebView has no network by design (ADR
    // 0002), and a remote font does not fail loudly -- it simply never
    // arrives, and the card renders a row of empty boxes on the one device
    // nobody is looking at while it is being built.
    //
    // The cloud is repeated rather than composed because a shared <symbol> and
    // three <use> elements is a second mechanism for the sake of 80 bytes.
    const CLOUD = 'M7.5 16h8.5a3.2 3.2 0 0 0 .3-6.4 4.6 4.6 0 0 0-8.8-1.1'
                + 'A3.6 3.6 0 0 0 7.5 16z';
    const GLYPHS = {
        clear: 'M16.5 12a4.5 4.5 0 1 1-9 0 4.5 4.5 0 1 1 9 0'
             + 'M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3'
             + 'M5.4 5.4l2.1 2.1M16.5 16.5l2.1 2.1M18.6 5.4l-2.1 2.1M7.5 16.5l-2.1 2.1',
        cloudy: CLOUD,
        rain: CLOUD + 'M9 18.5l-1 3M12.5 18.5l-1 3M16 18.5l-1 3',
        snow: CLOUD + 'M8 20h2M9 19v2M14 20h2M15 19v2',
        storm: CLOUD + 'M13 17.5l-3.5 4h3l-1.5 3',
        fog: 'M4 8h16M4 12.5h16M4 17h12',
    };

    // Returns null for a condition with no picture, and the caller appends
    // nothing -- there is no empty box and the card simply has no glyph.
    // format.js maps every code it does not know to 'unknown', which is a real
    // member of the set and lands here: a code open-meteo adds next year is
    // still named in full by the label underneath, and a made-up picture would
    // be the only thing on this panel that was not true.
    function renderGlyph(name) {
        const d = GLYPHS[name];
        if (!d) {
            return null;
        }
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'w-glyph');
        svg.setAttribute('viewBox', '0 0 24 24');
        // The label beside it says the same thing in words, so the picture is
        // decoration to anything that reads the DOM aloud.
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        svg.appendChild(path);
        return svg;
    }

    // Four lines where there was one sentence (T6.8). The card is the tallest
    // on the panel and held the least: the city, the temperature, the range
    // and the condition were all 24px in one colour, so the number a person
    // actually looks at was the same size as the name of the town they live
    // in.
    //
    // The order is the order it gets read in -- where, how warm, between what,
    // and what it is doing -- and only the second of those is large. The
    // glyph sits beside the temperature rather than above the city because
    // the two of them are the glance: 23 degrees and a cloud.
    //
    // One wrapper, because `.card > div` centres the card's only child in
    // whatever room is left under the title. Four children would each take an
    // auto margin and the group would come apart down the card.
    function renderWeather(weather) {
        els.weather.textContent = '';
        if (!weather) {
            return;
        }
        const body = el('div', null, 'w-body');

        const city = el('div', null, 'w-city');
        city.textContent = weather.city;

        const temp = el('div', null, 'w-temp');
        temp.textContent = `${formatTemp(weather.tempC)}°C`;
        const main = el('div', null, 'w-main');
        const glyph = renderGlyph(weatherGlyph(weather.code));
        main.append(...(glyph ? [glyph] : []), temp);

        const range = el('div', null, 'w-range');
        range.textContent = formatRange(weather.minC, weather.maxC);

        // Kept, not replaced. Seven glyphs cannot say "Thunderstorm, heavy
        // hail", and the label is what makes the card readable when the
        // picture is ambiguous -- rain and showers share one.
        const cond = el('div', null, 'w-cond');
        cond.textContent = weatherLabel(weather.code);

        body.append(city, main, range, cond);
        els.weather.appendChild(body);
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
        renderList(els.lists.quotes, payload.quotes || [], 'symbol', 'price', 'BRL');
        renderList(els.lists.fx, payload.fx || [], 'pair', 'rate', 'BRL',
                   formatRate, formatPair);
        renderList(els.lists.crypto, payload.crypto || [], 'symbol', 'price', 'USD');
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
