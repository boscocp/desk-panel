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

    // The words this render is drawing in (T6.11). Set at the top of render()
    // from the payload's `language`, which comes from the PC's config the same
    // way `theme` does -- so it is never read before it has been set, and a
    // panel that has not heard from the PC yet draws the panel's own default.
    //
    // A field rather than an argument threaded through nine functions: every
    // one of them would take it and three would use it, which is the shape
    // that gets a parameter quietly dropped in six months. `resumed` above is
    // kept for the same reason and set in the same place.
    let words = strings(null);

    // True for the length of one render: the panel has been dark, so the values
    // it is still showing are not evidence of anything and nothing may pulse
    // (T6.2). Core sets it -- see `context.resumed` in js/host.js -- because it
    // is the one thing about a render a theme cannot work out for itself: the
    // blackout hides `body` rather than emptying it, so last night's prices are
    // sitting in the markup at nine this morning looking exactly like a value
    // that just changed.
    //
    // Set unconditionally at the top of render(), so a render that throws
    // halfway cannot leave it stuck on.
    let resumed = false;

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
        // The titles are still drawn by ::before and they are no longer
        // written there (T6.11). `content: attr(data-title)` lets the word be
        // data while the box stays the stylesheet's, which is what keeps the
        // original reason for using ::before at all: renderWeather empties
        // #weather on every payload, and a real <h2> in there would go with
        // it. Set here and refreshed in render(), because the language can
        // change under a running panel exactly as the theme can.
        applyTitles({ quotes, fx, crypto, weather });

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
        stale.textContent = words.stale;
        stale.hidden = true;

        const panel = el('div', 'panel');
        panel.append(quotes, fx, crypto, weather, battery, stale);

        root.append(sidebar, panel);
        els = { root, clock, date, lists, weather, battery, stale };
    }

    // The four card titles, as data on the sections ::before reads them from.
    // Called from mount() and again from every render, because `language` is
    // config on the PC and a human editing that file must not have to restart
    // anything — the same promise `theme` makes (T3.12, ADR 0013).
    function applyTitles(sections) {
        for (const [id, section] of Object.entries(sections)) {
            section.setAttribute('data-title', words.titles[id]);
        }
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
        const before = shownPrices(list.scroller);
        list.scroller.textContent = '';
        for (const item of items) {
            const row = renderRow(formatLabel(item[labelField], currency), item[valueField],
                                  currency, item.changePct, format, item.history);
            // The row's own identity, and the only reason it is in the DOM: the
            // rows are thrown away and rebuilt on every payload, so the copy
            // that knows what PETR4 last cost is the one about to be deleted.
            // Reading it back out of the markup rather than keeping a Map here
            // means the record prunes itself -- a ticker removed from the PC's
            // config leaves nothing behind -- and means a theme swap, which
            // empties the root, starts with no history rather than with a
            // minute-old one that would pulse the whole panel at once.
            row.dataset.key = String(item[labelField]);
            pulseIfChanged(row.querySelector('.price'), before.get(row.dataset.key));
            list.scroller.appendChild(row);
        }
        applyScroll(list, items.length);
    }

    // What each row in this list is showing at the moment, keyed by symbol or
    // pair. Called immediately before the rows are replaced.
    function shownPrices(scroller) {
        const seen = new Map();
        for (const row of scroller.children) {
            const price = row.querySelector('.price');
            if (row.dataset.key && price) {
                seen.set(row.dataset.key, price.textContent);
            }
        }
        return seen;
    }

    // T6.2 step 2: a value that changed lifts toward --accent-hi for 280ms.
    //
    // The comparison is against the *rendered string*, not against the number
    // behind it, and that is deliberate on a panel: a price that moved by less
    // than the two decimals it is drawn with has not changed anything anybody
    // can see, and flashing it would be the panel claiming news it is not
    // showing.
    //
    // `undefined` means there was no row under this key a moment ago -- a first
    // render, a new ticker, a theme that has just been switched in. A new row
    // does not pulse: the whole panel arriving is not news about any one value.
    //
    // That covers a row that was *absent* and nothing else, which is why
    // `resumed` is a separate question and not the same one. The blackout
    // leaves every row mounted and merely hides it, so on the first render
    // after a night with the PC off this map is full, every price in it
    // differs, and the panel would flash all of them at once -- at nine in the
    // morning, in the second it comes back. The review of T6.2 is what found
    // that; this comment previously claimed the opposite outcome as a
    // property of the design.
    function pulseIfChanged(node, previous) {
        if (resumed) {
            return;
        }
        if (node && previous !== undefined && previous !== node.textContent) {
            node.classList.add('pulse');
        }
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
                                cssNumber(style, '--scroll-seconds-per-row'));

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

        // --- The seam (T6.9) ------------------------------------------------
        //
        // The card goes round now rather than walking down and back, and the
        // way it does that is the oldest trick there is: the list is drawn
        // twice and the box is moved by exactly one copy. When the first copy
        // has left the top, the second is sitting precisely where it started,
        // the animation restarts, and nothing on screen moved -- so the rows
        // appear to rise for ever out of a card three rows tall.
        //
        // Cloned here rather than in renderList, and only once the plan says
        // the card is actually going to move: a card that fits must not carry
        // a second invisible copy of itself, and applyScroll is the only place
        // that knows which is which. The clones are thrown away with the rest
        // of the rows on the next refresh, because renderList empties the
        // scroller before it rebuilds.
        //
        // They are also clones of rows that already carry their pulse class,
        // so a value that just changed flashes in both copies -- which is
        // what it must do, since either copy may be the one on screen.
        const rows = Array.from(list.scroller.children);
        for (const row of rows) {
            list.scroller.appendChild(row.cloneNode(true));
        }

        // Measured, not computed, and that is the difference between a seam
        // nobody can see and a one-pixel jolt every couple of minutes. The
        // distance wanted is the *pitch* of one copy: the rows carry a border
        // between them and not after the last one, so a copy inside a pair is
        // one border taller than a copy on its own, and `scrollHeight` before
        // cloning would be short by exactly that. The offset between a row and
        // its clone is the pitch by construction, whatever the borders,
        // margins and sub-pixel rounding happen to be.
        const pitch = rows.length
            ? list.scroller.children[rows.length].offsetTop - rows[0].offsetTop
            : 0;

        // Written on every refresh, and on a refresh that changed no rows these
        // are the same two strings as last time -- so the declaration does not
        // change, and a CSS animation whose declaration does not change is not
        // restarted. That, plus a scroller element mount() never replaces, is
        // the whole of step 4.
        list.scroller.style.setProperty('--scroll-distance', `${Math.round(pitch)}px`);
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
    // The panel's second icon set (T6.10). The battery line used to label its
    // two numbers with the word BAT and a degree sign, which is four
    // characters of the widest thing in the corner spent saying what a
    // fourteen-pixel picture says at a glance from across the room.
    //
    // Same 24-unit box and same stroke-only construction as the weather
    // glyphs above, so they take the card's ink and never need a palette --
    // which is what makes the battery line's three temperature colours
    // (T5.4) colour the icons too, for free.
    const ICONS = {
        // A cell lying on its side with its terminal on the right. The body is
        // drawn as one rounded rectangle rather than as a path so that the
        // fill below has something exact to sit inside.
        // Body and terminal, with a real gap between them: the first cut put
        // the terminal two units off a body that ran to 18, and at 18px that
        // is a pixel and a half -- the nub vanished into the outline and the
        // icon read as a pill. The body stops at 16.8 and the terminal stands
        // at 18.6, which is about the proportion a real cell has.
        battery: 'M4 8.4h11.2a1.6 1.6 0 0 1 1.6 1.6v3.6a1.6 1.6 0 0 1-1.6 1.6H4'
               + 'a1.6 1.6 0 0 1-1.6-1.6V10A1.6 1.6 0 0 1 4 8.4z'
               + 'M18.6 10.6v2.8',
        // Bulb and stem. The stem stops short of the bulb's centre so the two
        // read as one object at 14px rather than as a circle with a line
        // through it.
        thermometer: 'M12 3.5a2 2 0 0 1 2 2v7.1a4 4 0 1 1-4 0V5.5a2 2 0 0 1 2-2z'
                   + 'M12 9v5.5',
    };

    // One <svg> with one path in it. Both icon sets go through this: the only
    // things that differ are the drawing and the class, and a second copy of
    // the namespace incantation is how the two sets start drifting.
    function svgIcon(d, className) {
        if (!d) {
            return null;
        }
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', className);
        svg.setAttribute('viewBox', '0 0 24 24');
        // The value beside it says the same thing, so the picture is
        // decoration to anything that reads the DOM aloud.
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        svg.appendChild(path);
        return svg;
    }

    function renderGlyph(name) {
        return svgIcon(GLYPHS[name], 'w-glyph');
    }

    // The battery icon, with its charge drawn inside it (T6.10).
    //
    // The bar is the one place this set departs from the weather glyphs, and
    // it is the reason the icon is worth more than the word it replaced: a
    // filled outline is read before a two-digit number is, from the distance
    // this panel is actually looked at. It says the same thing the number
    // says, which is exactly what the sparkline does beside a price.
    //
    // Clamped, because a level over 100 arrives from a phone that has just
    // been plugged in and a bar sticking out of its own battery looks like a
    // rendering bug rather than a full charge.
    function renderBatteryIcon(level) {
        const svg = svgIcon(ICONS.battery, 'b-icon');
        if (!svg) {
            return null;
        }
        const fraction = Math.max(0, Math.min(1, level / 100));
        if (fraction > 0) {
            const fill = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            // The body's *inner* edge, which is not the path's coordinates: a
            // 1.6-unit stroke sits half outside the line it is drawn on, so
            // the usable inside runs 3.2..16 across and 9.2..14.8 down. A bar
            // drawn to the path itself would sit under its own outline and
            // read as one solid lozenge at every level above about 80%.
            fill.setAttribute('x', '3.2');
            fill.setAttribute('y', '9.2');
            fill.setAttribute('width', String(Math.round(12.8 * fraction * 100) / 100));
            fill.setAttribute('height', '5.6');
            fill.setAttribute('rx', '0.7');
            fill.setAttribute('class', 'b-fill');
            svg.appendChild(fill);
        }
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
        // Read before the card is emptied, for the same reason the lists read
        // theirs: the only record of what the panel was showing is the markup
        // that is about to be thrown away.
        const shownTemp = els.weather.querySelector('.w-temp');
        const before = shownTemp ? shownTemp.textContent : undefined;
        els.weather.textContent = '';
        if (!weather) {
            return;
        }
        const body = el('div', null, 'w-body');

        const city = el('div', null, 'w-city');
        city.textContent = weather.city;

        const temp = el('div', null, 'w-temp');
        temp.textContent = `${formatTemp(weather.tempC)}°C`;
        // The only value outside the lists worth a pulse. It is the second
        // largest number on the panel and the server refreshes it on its own
        // clock, so it can change on a cycle where nothing else did -- which is
        // exactly the case a reader would otherwise miss.
        pulseIfChanged(temp, before);
        const main = el('div', null, 'w-main');
        const glyph = renderGlyph(weatherGlyph(weather.code));
        main.append(...(glyph ? [glyph] : []), temp);

        const range = el('div', null, 'w-range');
        range.textContent = formatRange(weather.minC, weather.maxC);

        // Kept, not replaced. Seven glyphs cannot say "Trovoada com granizo
        // forte", and the label is what makes the card readable when the
        // picture is ambiguous -- rain and showers share one.
        const cond = el('div', null, 'w-cond');
        cond.textContent = words.weather[weather.code] || words.unknown;

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
        const fields = batteryFields(battery);
        if (!fields) {
            return;
        }
        const line = el('div');
        // The whole line takes the colour, not just the number: at 20px in a
        // corner, a single re-coloured word is easy to miss and the
        // temperature is right there to explain it. The icons are stroked in
        // currentColor, so they take the band's colour with the text.
        //
        // 'normal' is set as a class rather than left empty so the three bands
        // read as three states in the DOM; the stylesheet gives it nothing.
        line.className = tempClass(battery.tempC);

        // Icon, value, icon, value (T6.10). The word BAT and the ° are gone;
        // what is left in the corner is two pictures and two numbers, which
        // is the least this line can be and still say what it says.
        const level = el('span', null, 'b-value');
        level.textContent = fields.level;
        line.append(...[renderBatteryIcon(battery.level)].filter(Boolean), level);

        if (fields.temp) {
            const temp = el('span', null, 'b-value');
            temp.textContent = fields.temp;
            line.append(...[svgIcon(ICONS.thermometer, 'b-icon')].filter(Boolean), temp);
        }

        // Still a word, and deliberately: there is no picture for "this phone
        // is now running its own battery down" that a stranger would read the
        // way they read a battery outline, and getting it wrong is the one
        // thing in this corner that matters (ADR 0014).
        if (fields.unplugged) {
            const note = el('span', null, 'b-note');
            note.textContent = words.unplugged;
            line.appendChild(note);
        }
        els.battery.appendChild(line);
    }

    // `payload` is null before the first word from the PC: the skeleton is
    // built and the cards are empty, which is what the panel looked like in
    // that state before T6.7 too.
    function render(payload, root, context) {
        // Before ensure(), which may mount and which reads `words` for the
        // titles and the badge. Unconditional and before the early return, so
        // a payload-less render still draws the skeleton in the right
        // language and a render that throws halfway cannot leave the panel
        // speaking the last payload's.
        words = strings(payload && payload.language);
        ensure(root);
        resumed = !!(context && context.resumed);
        // The language is the one thing here that can change without the
        // markup changing, so it is reapplied rather than left to mount().
        applyTitles({
            quotes: els.lists.quotes.section,
            fx: els.lists.fx.section,
            crypto: els.lists.crypto.section,
            weather: els.weather,
        });
        els.stale.textContent = words.stale;
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

        // The language the PC asked for, not the host's (T6.11). `undefined`
        // means "whatever this runtime thinks", which on the device is the
        // phone's system locale and in a browser is the developer's -- so the
        // panel used to say MONDAY, FEBRUARY 23 on a desk in Brazil whose
        // every other word was Portuguese, and the two would drift apart
        // again the moment somebody changed one of them.
        els.date.textContent = now.toLocaleDateString(words.tag, {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }

    window.DeskPanel.defineTheme('neon', { render, tick });
})();
