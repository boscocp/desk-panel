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

    // The words this render is drawing in (T6.11). Set at the top of render()
    // from the payload's `language`, exactly as the neon theme does it: a
    // field rather than an argument threaded through every function, because
    // most of them would take it and not use it.
    let words = strings(null);

    // The last `agenda` the PC sent and the minute the line was drawn for, so
    // tick() can move the countdown on without a payload (T9.1) -- the same
    // arrangement as neon, because it is the same rule: the phone's clock
    // decides, and the PC is never asked twice for one answer.
    let agenda = undefined;
    let agendaMinute = null;

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
        stale.textContent = words.stale;
        stale.hidden = true;

        const header = el('header', null, 'header');
        header.append(clock, date, stale);

        // Reserved for the shortcut buttons, as in neon: the space exists
        // before the buttons do.
        const shortcuts = el('div', 'shortcuts');

        const quotes = column('quotes', words.titles.quotes);
        const fx = column('fx', words.titles.fx);
        const crypto = column('crypto', words.titles.crypto);
        const weather = column('weather', words.titles.weather);

        const grid = el('div', null, 'grid');
        grid.append(quotes.section, fx.section, crypto.section, weather.section);

        const battery = el('section', 'battery');

        // The device line and the buttons share one row rather than stacking.
        // Stacked, the 56px targets cost the columns 66px of height and
        // check_layout.py reported #quotes hiding 42px of rows without
        // scrolling -- a card eating a row in silence, which is the one thing
        // T6.6 forbids. Side by side the row is as tall as the buttons and
        // nothing else moved. The buttons are the taller of the two, so the
        // line centres against them.
        const footer = el('div', null, 'footer');
        // The next meeting (T9.1). neon gives it a card; this theme has no
        // card to give, and a fifth column would cost the four it has their
        // width, so it is one line in the row that already holds the other
        // things that are about the owner's machine and day. Between the
        // battery and the buttons, and the one of the three allowed to shrink.
        const agenda = el('section', 'agenda');
        agenda.setAttribute('data-reserved', '');
        footer.append(battery, agenda, shortcuts);

        root.append(header, grid, footer);
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
            shortcuts,
            agenda,
        };
        // The signature renderShortcuts compares against describes markup that
        // has just been thrown away. mount() runs again whenever host.js empties
        // the root -- a theme switch away and back is the ordinary case -- and a
        // stale signature would match the ids that are still enabled and return
        // early, leaving the strip empty on a panel that had buttons a minute
        // ago.
        drawnActions = null;
    }

    // --- The shortcut buttons (T8.2) ---------------------------------------
    //
    // The same contract as neon, deliberately drawn differently: a word and
    // no picture, in a row, with the result said in text rather than in
    // colour. That is this theme's whole job -- if the buttons work here too
    // then the action contract really is a contract and not neon's markup
    // wearing a name (T6.7's manual check).
    //
    // What is *not* different is the 56px target. It is a fact about a finger
    // on a phone at arm's length, not a matter of taste, so both themes carry
    // it and docs/THEMING.md says so.
    let drawnActions = null;

    function renderShortcuts(actions) {
        const wanted = shortcutsFor(actions, words.tag);
        const signature = wanted.map((s) => s.id + ':' + s.label).join(',');
        if (signature === drawnActions) {
            return;
        }
        drawnActions = signature;
        els.shortcuts.textContent = '';
        for (const shortcut of wanted) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'shortcut';
            button.id = 'action-' + shortcut.id;
            button.dataset.action = shortcut.id;
            button.title = shortcut.hint;
            button.textContent = shortcut.label;
            applyState(button, 'unknown');
            button.addEventListener('click', () => press(button, shortcut));
            els.shortcuts.appendChild(button);
        }
    }

    // The last result, never a state (T8.2 step 7). Here it is a word after
    // the caption rather than a colour, because this theme has no palette to
    // say it with -- which makes it the honest test of whether the rule is
    // about the rule or about neon's CSS.
    // The state the PC last reported, said in a word. neon draws a cross; this
    // theme has no pictures, so it says it -- which is the point of the theme
    // existing, and the check that the contract is about the contract.
    //
    // `unknown` is the resting state and shows nothing: the panel has not
    // asked, and a theme that printed "com som" before anyone pressed anything
    // would be making the claim ADR 0015 forbids.
    function applyState(button, state) {
        button.dataset.state = state;
        const suffix = state === 'muted' ? words.actionMuted
            : state === 'unmuted' ? words.actionUnmuted : '';
        button.title = suffix ? words.actionHint + ' \u2014 ' + suffix : words.actionHint;
    }

    const ACK_MS = 1200;

    // The pending fade per button, so a new press can cancel the old one:
    // otherwise the previous acknowledgement's timer fires part-way through
    // this press and replaces "SOM ..." with "SOM" on a button that is still
    // waiting to hear.
    const fading = new Map();

    function press(button, shortcut) {
        if (button.dataset.busy) {
            return;
        }
        button.dataset.busy = '1';
        button.textContent = shortcut.label + ' ...';
        if (fading.has(button)) {
            window.clearTimeout(fading.get(button));
            fading.delete(button);
        }
        let settled = false;
        const settle = (ok, state) => {
            // Once: core answers a refusal through the callback *and* through
            // its return value, so both arms below can run for one press.
            if (settled) {
                return;
            }
            settled = true;
            delete button.dataset.busy;
            // Only a press that worked may move the state. A failure says so
            // and leaves the last thing the PC told us alone -- guessing a
            // flip after a failure is how a panel ends up claiming a
            // microphone is off while it is live.
            if (ok) {
                applyState(button, state || 'unknown');
            }
            button.textContent = ok ? shortcut.label + ' ok' : shortcut.label + ' ' + words.actionFailed;
            fading.set(button, window.setTimeout(() => {
                fading.delete(button);
                // Back to the caption plus whatever the PC last said, which is
                // this theme's version of neon's cross: it persists, while the
                // ok/failed acknowledgement above does not.
                const state = button.dataset.state;
                const suffix = state === 'muted' ? words.actionMuted
                    : state === 'unmuted' ? words.actionUnmuted : '';
                button.textContent = suffix ? shortcut.label + ' \u2014 ' + suffix
                    : shortcut.label;
            }, ACK_MS));
        };
        if (!DeskPanel.invoke(shortcut.id, settle)) {
            settle(false);
        }
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
        if (!plan || !worthScrolling(content - available, rowHeight)) {
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
        cond.textContent = words.weather[weather.code] || words.unknown;
        els.weather.append(city, temp, range, cond);
        // The chance of rain as a sentence (T6.15). The neon theme draws a
        // drop and a number and was asked for without a word; this theme has
        // no pictures on purpose, so here the word is the whole of it -- which
        // is why `rainChance` is in format.js as wording rather than only as an
        // accessible label.
        const chance = chanceOfRain(weather);
        if (chance !== null) {
            const rain = el('div', null, 'w-chance');
            rain.textContent = `${words.rainChance}: ${formatPercent(chance)}`;
            els.weather.appendChild(rain);
        }
        // The moon as a sentence, because this theme draws no pictures on
        // purpose (T6.13). The neon theme spends a filled path on the phase
        // and puts the name in the glyph's accessible label; here the name
        // *is* the panel, so it is written out with the percentage beside it.
        // A theme is free to answer the data however it likes, and "in words"
        // is an answer.
        const moon = moonFields(weather.moon, words);
        if (moon) {
            const line = el('div', null, 'w-moon');
            const pct = formatPercent(moon.illum);
            line.textContent = pct ? `${moon.label}, ${pct}` : moon.label;
            els.weather.appendChild(line);
        }
    }

    function renderBattery(battery) {
        els.battery.textContent = '';
        const text = formatBattery(battery, words.tag);
        if (!text) {
            return;
        }
        const line = el('div', null, tempClass(battery.tempC));
        line.textContent = text;
        els.battery.appendChild(line);
    }

    // One line: the countdown, then the title, then which account needs
    // reconnecting, joined by a separator this theme already uses nowhere
    // else so it cannot be mistaken for part of a title. Plain text, no
    // colour for "in progress": the words say it ("agora · até 14:30"), which
    // is the honest test that the contract carries it and neon's palette
    // does not have to.
    function renderAgenda(now) {
        agendaMinute = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
        const fields = agendaFields(agenda, now, words.tag);
        if (!fields) {
            els.agenda.textContent = '';
            els.agenda.setAttribute('data-reserved', '');
            return;
        }
        els.agenda.removeAttribute('data-reserved');
        // `when` is empty when every account failed and there is no event:
        // the failure is then the whole line, not "nada à vista — ...".
        const parts = fields.when ? [fields.when] : [];
        if (fields.title) {
            parts.push(fields.title);
        }
        if (fields.failed) {
            parts.push(fields.failed);
        }
        // In a line of its own rather than on the section, so the ellipsis
        // clips inside a box whose width the footer already gave it: an
        // ellipsis on the section itself is content wider than its box, which
        // e2e/layout/measure.js reports as clipped -- correctly, since it
        // cannot tell a deliberate ellipsis from a card eating its text.
        const line = el('div', null, 'a-line');
        line.textContent = parts.join(' — ');
        line.title = line.textContent;
        els.agenda.textContent = '';
        els.agenda.appendChild(line);
    }

    function render(payload, root) {
        // Before ensure(), which may mount and which reads `words` for the
        // column headings and the badge (T6.11).
        words = strings(payload && payload.language);
        ensure(root);
        // The headings are built by mount() and the language can change under
        // a running panel, so they are refreshed here as well -- the same
        // thing the neon theme does with its data-title attributes. Found by
        // the id the column was built with rather than kept in `els`, which
        // would be a fifth reference to the same four sections for the sake
        // of four querySelector calls a minute.
        for (const id of Object.keys(words.titles)) {
            const heading = root.querySelector(`#${id} .col-title`);
            if (heading) {
                heading.textContent = words.titles[id];
            }
        }
        els.stale.textContent = words.stale;
        if (!payload) {
            return;
        }
        fill(els.quotes, payload.quotes || [], 'symbol', 'price', 'BRL', formatPrice);
        fill(els.fx, payload.fx || [], 'pair', 'rate', 'BRL', formatRate, formatPair);
        fill(els.crypto, payload.crypto || [], 'symbol', 'price', 'USD', formatPrice);
        renderWeather(payload.weather);
        renderBattery(payload.battery);
        renderShortcuts(payload.actions);
        agenda = payload.agenda;
        renderAgenda(new Date());
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
        if (agendaMinute !== `${hours}:${minutes}`) {
            renderAgenda(now);
        }
        // The language the PC asked for, not the host's (T6.11). `undefined`
        // means "whatever this runtime thinks", which on the device is the
        // phone's system locale and in a browser is the developer's -- so the
        // panel used to say MONDAY, FEBRUARY 23 on a desk in Brazil whose
        // every other word was Portuguese, and the two would drift apart
        // again the moment somebody changed one of them.
        els.date.textContent = now.toLocaleDateString(words.tag, {
            weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
        });
    }

    window.DeskPanel.defineTheme('plain', { render, tick });
})();
