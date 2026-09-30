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

    // The last `agenda` the PC sent, and the minute the card was last drawn
    // for (T9.1). The countdown moves once a minute and the payload arrives
    // once a minute, on unrelated clocks, so the card is redrawn from tick()
    // whenever the minute turns -- from the instants already on hand, never
    // by asking the PC again (ADR 0017: the phone's clock decides).
    let agenda = undefined;
    let agendaMinute = null;

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
        // The device line, under the date (T6.12). It used to sit in the foot
        // of the weather card, which put the handset's temperature and the
        // room's in one box -- two numbers in degrees, six lines apart, about
        // different things. Read from the chair that is a question rather than
        // a diagnostic, and the answer asked for was to move it to the one
        // place on the panel that is already about the machine rather than
        // about the world: under the clock.
        const battery = el('section', 'battery');
        const clockContainer = el('div', 'clock-container');
        clockContainer.append(clock, date, battery);

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
        // Reserved, visibly (T6.12). #shortcuts makes the same promise in the
        // sidebar and makes it invisibly, which is right for a strip that will
        // hold buttons; this one was asked for as a *card*, so the owner can
        // see that the panel has somewhere to put a meeting before T9.1 puts
        // one there. data-reserved is what tells e2e/layout/measure.js that
        // holding no text is this card's intended state rather than the fault
        // T6.1 added the empty-section check for.
        const agenda = el('section', 'agenda', 'card');
        agenda.setAttribute('data-reserved', '');
        // The titles are still drawn by ::before and they are no longer
        // written there (T6.11). `content: attr(data-title)` lets the word be
        // data while the box stays the stylesheet's, which is what keeps the
        // original reason for using ::before at all: renderWeather empties
        // #weather on every payload, and a real <h2> in there would go with
        // it. Set here and refreshed in render(), because the language can
        // change under a running panel exactly as the theme can.
        applyTitles({ quotes, fx, crypto, weather, agenda });

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
        const stale = el('div', 'stale-badge');
        stale.textContent = words.stale;
        stale.hidden = true;
        // A real element rather than a second pseudo-element beside the
        // title's ::before, so e2e/layout/measure.js sees its ink. Outside
        // .card-body, which renderList refills; absolute, so it takes no row
        // of the card's column.
        const closed = el('div', null, 'market-closed');
        closed.hidden = true;
        quotes.appendChild(closed);

        // The right-hand track, split down the middle (T6.12). A wrapper
        // rather than two grid areas, because the two cards are meant to be
        // exactly equal and the left column's rows are not: 1.3fr for the B3
        // card against 1fr for the other two, so any pair of rows borrowed
        // from that template would divide this column 58/42 and look like a
        // mistake. Nested, the halves are 1fr and 1fr and the arithmetic is
        // the browser's.
        const side = el('div', 'side');
        side.append(weather, agenda);

        const panel = el('div', 'panel');
        panel.append(quotes, fx, crypto, side, stale);

        root.append(sidebar, panel);
        els = { root, clock, date, lists, weather, agenda, battery, stale, shortcuts, closed };
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
    // Markup, so they are the theme's. Core's half is one call:
    // `DeskPanel.invoke(id, done)`, which decides whether a press is possible
    // at all -- the PC being away, the id not being one the server enabled,
    // there being no bridge because this is a browser -- and reaches Java.
    // Nothing here knows any of that, and nothing here knows a URL.
    //
    // Rebuilt only when the set of ids changes, which is almost never: the
    // payload arrives once a minute and `actions` comes from a file a human
    // edits. Rebuilding on every payload would throw away a button mid-press
    // and lose the acknowledgement it was showing.
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
            els.shortcuts.appendChild(buildButton(shortcut));
        }
    }

    function buildButton(shortcut) {
        // A real <button>: it is focusable, it fires on a tap without a
        // 300ms wait, and it is announced as a button. A styled <div> with a
        // click handler is none of those and is the shape this would have
        // taken if the CSS had been written first.
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'shortcut';
        button.id = 'action-' + shortcut.id;
        // The id is data, never part of a string that becomes a request. The
        // click handler below reads it back and hands it to core, which
        // matches it against what the PC sent; Java matches it again against
        // its own allowlist (ADR 0015, Actions.java).
        button.dataset.action = shortcut.id;
        button.title = shortcut.hint;

        // No caption. Asked for from the chair, and the icon carries the
        // whole message now -- which is what makes room for it to be big
        // enough to read across a desk. The word has not gone away, it has
        // moved to where it belongs for a picture: the accessible name, which
        // is also what `title` shows and what a screen reader says.
        const icon = svgIcon(ICONS[shortcut.id], 's-icon');
        if (icon) {
            // The cross that says *muted*, drawn once and hidden until the PC
            // says so. Built here rather than on each result so a state change
            // is one attribute and not a rebuild of the icon under the finger.
            icon.appendChild(svgPath(ICONS.mutedCross, 's-cross'));
            button.appendChild(icon);
        }

        applyState(button, shortcut, 'unknown');
        button.addEventListener('click', () => press(button, shortcut));
        return button;
    }

    // What the icon claims, and the claim is narrow on purpose.
    //
    // `unknown` is the resting state and the honest one: the panel has not
    // asked, so it draws the device and no cross. After a press the PC reports
    // what its mixer actually holds -- measured, not inferred (ADR 0015's
    // amendment) -- and the cross follows that.
    //
    // **It is the last known state, not a live one.** Somebody at the keyboard
    // can mute after the panel last asked and nothing tells the phone. The
    // accessible name says so rather than the picture pretending otherwise,
    // which is the same bargain the stale badge makes for a price.
    function applyState(button, shortcut, state) {
        button.dataset.state = state;
        const suffix = state === 'muted' ? words.actionMuted
            : state === 'unmuted' ? words.actionUnmuted : '';
        button.setAttribute(
            'aria-label',
            shortcut.label + ' \u2014 ' + shortcut.hint + (suffix ? ' (' + suffix + ')' : ''));
    }

    // Two different things are drawn on a press and they have different
    // lifetimes, which is the whole reason this is fiddly:
    //
    //   the **result**  -- did the request work. A brief colour, and it fades.
    //   the **state**   -- what the mixer now holds. The cross, and it stays.
    //
    // T8.2 step 7 said the button shows the result and never a state, because
    // the panel could not know one: every Linux mixer toggles in silence. The
    // chair asked for the cross, so the server measures the state with a
    // second read-only command instead of inferring it, and the cross is the
    // PC's own answer rather than the panel's guess.
    //
    // What has not changed is the honesty rule underneath: the cross is the
    // **last known** state, not a live one, and a failed press leaves it
    // exactly where it was rather than flipping it. A button that said the
    // microphone was off while it was live would be a privacy failure, and
    // guessing after a failure is precisely how that happens.
    const ACK_MS = 1200;

    // The pending fade per button, so a new press can cancel the old one.
    const fading = new Map();

    function press(button, shortcut) {
        if (button.dataset.busy) {
            // A second tap while one is in flight is dropped rather than
            // queued. Queued presses on a toggle are how twenty taps become
            // an unknown number of toggles arriving over the next minute.
            return;
        }
        button.dataset.busy = '1';
        button.classList.remove('ok', 'err');
        button.classList.add('sending');
        // The previous press's fade, cancelled. Without this, the timer from
        // an acknowledgement that has not finished yet fires part-way through
        // *this* press and puts the caption back -- which is the wrong caption
        // for a button that is currently sending, and on the second tap of a
        // pair it wipes the acknowledgement that has just appeared.
        if (fading.has(button)) {
            window.clearTimeout(fading.get(button));
            fading.delete(button);
        }
        let settled = false;
        const settle = (ok, state) => {
            // Once. Core answers a refusal through the callback *and* through
            // its return value, so both arms below can run for one press.
            if (settled) {
                return;
            }
            settled = true;
            delete button.dataset.busy;
            button.classList.remove('sending');
            button.classList.add(ok ? 'ok' : 'err');
            // Only a press that worked may move the cross. A failure says so
            // with the flash and leaves the state alone: the last thing the PC
            // told us is still the best thing known, and inventing a flip here
            // is how a cross ends up lying about a live microphone.
            if (ok) {
                applyState(button, shortcut, state || 'unknown');
            }
            fading.set(button, window.setTimeout(() => {
                fading.delete(button);
                button.classList.remove('ok', 'err');
            }, ACK_MS));
        };
        // false means core refused outright -- offline, no bridge, or an id
        // the PC did not send -- and no result is coming. Settling here is
        // what stops a button sitting in `sending` for ever.
        if (!DeskPanel.invoke(shortcut.id, settle)) {
            settle(false);
        }
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
        if (!plan || !worthScrolling(content - available, rowHeight)) {
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
        // A clear sky after dark. Stars rather than a moon: the moon has its
        // own permanent place on this card with its phase and its percentage,
        // and drawing it twice would be the card saying one thing in two
        // sizes. Three of them, unevenly placed -- an even row reads as a
        // dotted line rather than as a sky.
        stars: 'M7 7.5v3M5.5 9h3M16 5v2.5M15 6.25h2.5'
             + 'M12.5 14v3.5M10.75 15.75h3.5',
        // And a cloudy night: the cloud is the subject, so the moon behind it
        // is small and is a crescent whatever tonight's phase is. This glyph
        // answers "what is the sky doing", not "which moon is up".
        'cloudy-night': CLOUD + 'M17.5 5.5a3 3 0 1 0 3 3 3.6 3.6 0 0 1-3-3',
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
        // A cell lying on its side, drawn as an outline with a solid terminal
        // standing clear of it on the right.
        //
        // **Second cut**, because the first was reported as hard to read from
        // the chair and it is worth saying exactly why. The body ran from 2.4
        // to 16.8 and the charge was drawn to its inner edge, so above about
        // 60% the fill met the outline and the whole thing read as one solid
        // lozenge -- a pill, not a battery. The terminal was a 2.8-unit stroke
        // one and a half pixels off the body, which at this size disappeared
        // into it.
        //
        // So: the charge keeps a visible gap inside the outline at every level
        // (see renderBatteryIcon), and the terminal is a filled rounded
        // rectangle with real air around it rather than a tick. A battery is
        // recognised by its silhouette -- a long box with a small nub -- and
        // the nub is the half that was missing.
        battery: 'M3.6 7.6h11.8a1.8 1.8 0 0 1 1.8 1.8v5.2a1.8 1.8 0 0 1-1.8 1.8H3.6'
               + 'a1.8 1.8 0 0 1-1.8-1.8V9.4a1.8 1.8 0 0 1 1.8-1.8z',
        batteryCap: 'M19.2 10.2h1.2a.8.8 0 0 1 .8.8v2a.8.8 0 0 1-.8.8h-1.2z',

        // Bulb, column and three scale marks.
        //
        // **Second cut**, for the same reason. The first was an outline bulb
        // with a hairline stem through it, which at this size is a keyhole or
        // a lowercase i -- there was nothing in it that says *thermometer*
        // except the proportion. What says it is the silhouette plus two
        // things the outline did not have: a **filled** bulb and column, which
        // is what mercury looks like, and a scale down one side, which nothing
        // else on a panel has.
        thermometer: 'M12 3a2.4 2.4 0 0 1 2.4 2.4v7.4a4.4 4.4 0 1 1-4.8 0V5.4A2.4 2.4 0 0 1 12 3z',
        thermometerTicks: ['M15.6 7.4h2.2', 'M15.6 10.2h1.5', 'M15.6 13h2.2'],

        // The two shortcut buttons (T8.2), keyed by the server's action id so
        // `ICONS[shortcut.id]` is the whole lookup and an id with no drawing
        // gets a button with a caption and no picture rather than an empty
        // <svg> holding a flex basis open.
        //
        // Silhouettes, not outlines of devices. The two sit side by side and
        // the failure they have to avoid is a mis-tap, so what matters is that
        // they are distinguishable at a glance across a desk: a squat cone
        // pointing right, and a tall capsule on a stand. That is the same
        // argument the battery and thermometer icons above lost twice before
        // it was taken seriously.
        //
        // **The device only.** The cross that says *muted* is a separate path
        // (`mutedCross`), drawn over the top and only when the PC has actually
        // said so -- asked for from the chair, and honest only because the
        // server measures the state rather than guessing it (ADR 0015's
        // amendment). An icon that baked the cross in would be claiming a
        // state on every render.
        'mute-audio': 'M4 9.5h3.2L12 5.4v13.2L7.2 14.5H4a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1z',
        'mute-mic': 'M12 3.2a2.6 2.6 0 0 1 2.6 2.6v5.4a2.6 2.6 0 1 1-5.2 0V5.8'
                  + 'A2.6 2.6 0 0 1 12 3.2zM6.4 11.2a5.6 5.6 0 0 0 11.2 0M12 16.8v3.4'
                  + 'M9.2 20.2h5.6',
        // One stroke for both, in the top-right quadrant where neither device
        // has ink: a cross over the middle of the microphone would eat the
        // shape that identifies it.
        mutedCross: 'M16.4 8.4l5 5M21.4 8.4l-5 5',
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
        svg.appendChild(svgPath(d, null));
        return svg;
    }

    // Shared by the icon builders below, which add a second and a third path
    // to an <svg> svgIcon has already made -- a filled terminal, a scale.
    function svgPath(d, className) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        if (className) {
            path.setAttribute('class', className);
        }
        return path;
    }

    // A <rect> in the SVG namespace, which `document.createElement` cannot
    // make: an HTML <rect> inside an <svg> is parsed, kept, and never drawn.
    function svgRect(x, y, width, height, rx, className) {
        const r = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        r.setAttribute('x', String(x));
        r.setAttribute('y', String(y));
        r.setAttribute('width', String(width));
        r.setAttribute('height', String(height));
        r.setAttribute('rx', String(rx));
        r.setAttribute('class', className);
        return r;
    }

    // The picture, and the words that go with it (T6.12).
    //
    // The condition used to be drawn under the range as a line of prose and is
    // not drawn at all any more: the glyph beside the temperature says the same
    // thing in a quarter of the room, and the right-hand column is now two
    // cards deep rather than one. What the label still is, is the truth the
    // picture rounds off -- seven glyphs cannot tell `Pancadas` from `Chuva`,
    // and format.js keeps one name per WMO code. So it becomes the glyph's
    // accessible name rather than disappearing: anything reading this DOM
    // aloud, or reading it back in a test, still gets the exact condition.
    // --- The moon (T6.13) --------------------------------------------------
    //
    // The one shape in this set that cannot be a stroked outline. A circle with
    // an outline is a circle; what says *moon* is the lit part being filled and
    // the dark part not being drawn at all. So it is one filled path made of
    // two arcs -- the limb and the terminator -- which is also why the same
    // path draws every phase from a single number.
    //
    // Geometry, in the 24x24 box the rest of the set uses: centre (12, 12),
    // radius 9. The limb is a semicircle on the lit side. The terminator is
    // half an ellipse with the same vertical radius and a horizontal one of
    // r * |1 - 2k| for a lit fraction k, which is the projection of the
    // day/night line onto the disc:
    //
    //   k = 0.5  -> rx = 0, a straight edge, exactly half lit
    //   k > 0.5  -> the terminator bulges away from the lit side (gibbous)
    //   k < 0.5  -> it bulges into it (crescent)
    //
    // Whether it bulges in or out is the arc's sweep flag rather than a second
    // path, which is what keeps this one `d` string.
    const MOON_R = 9;

    // **Southern hemisphere.** A waxing moon is lit on the *left* here, and on
    // the right from Europe or North America. This panel is in Sao Paulo
    // (server/config.toml's city is what the weather is for), so it draws the
    // southern convention; on a panel moved north every phase would be
    // mirrored. Documented rather than configured: it is one constant, and the
    // day somebody runs this in Lisbon is the day to make it a setting.
    const MOON_SOUTHERN = true;

    function moonPath(illum, waxing) {
        const k = Math.max(0, Math.min(1, (illum == null ? 50 : illum) / 100));
        const cx = 12;
        const top = 12 - MOON_R;
        const bottom = 12 + MOON_R;
        // Lit on the left for a waxing moon in the south, on the right for a
        // waning one; mirrored in the north.
        const litLeft = MOON_SOUTHERN ? waxing : !waxing;
        // The limb: down the lit side. Sweep 0 goes counter-clockwise, which
        // from the top of a circle is the left-hand side.
        const limbSweep = litLeft ? 0 : 1;
        const rx = Math.abs(1 - 2 * k) * MOON_R;
        // The terminator bulges outward past the middle (gibbous) and inward
        // before it (crescent). Outward means it keeps going the same way
        // round as the limb.
        const gibbous = k > 0.5;
        const termSweep = gibbous ? limbSweep : 1 - limbSweep;
        return `M ${cx} ${top}`
             + ` A ${MOON_R} ${MOON_R} 0 0 ${limbSweep} ${cx} ${bottom}`
             + ` A ${rx.toFixed(2)} ${MOON_R} 0 0 ${termSweep} ${cx} ${top}`
             + ' Z';
    }

    // The whole element: the shape, filled, plus how much of it is lit.
    //
    // Permanent rather than only after dark, which is what was asked for from
    // the chair: the phase is the slowest-moving fact on this panel and the one
    // a reader can check against the sky. It sits on the min/max line because
    // that line is the card's narrowest -- `18.3 / 28.5` leaves about half the
    // width free -- so the moon costs the card no height at all, and the card
    // has 6.6px of slack (see the budget in theme.css).
    //
    // A new moon is drawn as a thin outline rather than as nothing: an empty
    // slot reads as a missing icon, and "the moon is not lit tonight" is a
    // fact worth a shape.
    function renderMoon(moon) {
        if (!moon) {
            return null;
        }
        const wrap = el('div', null, 'w-moon');
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'w-moon-glyph');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('role', 'img');
        // The percentage beside it says how much; the name is the half no
        // number carries, and at 24px a waxing crescent and a waning one are
        // mirror images. Same reason the weather glyph kept its words in
        // format.js when T6.12 took the condition line away.
        svg.setAttribute('aria-label', moon.label);
        // The whole disc first, as a thin ring, and then the lit part filled on
        // top of it. Both, always -- and the ring is what makes the phase
        // legible rather than decorative.
        //
        // The first cut drew only the lit shape and it was measured on the
        // device: at 85% a gibbous moon is a disc with a shallow bite out of
        // one side, 16 units wide against a full 18, and at 22px that reads as
        // a plain oval. Nothing said *phase*. With the ring behind it the eye
        // has the full circle to compare against, so 85% reads as almost full
        // and 20% reads as a crescent inside a moon instead of as a sliver
        // floating on its own.
        //
        // A new moon is then not a special case at all: it is the ring with
        // nothing filled in, which is exactly what a new moon is.
        svg.appendChild(svgPath(
            'M 12 3 A 9 9 0 1 1 11.99 3 Z', 'w-moon-disc'));
        if (moon.phase !== 'new') {
            svg.appendChild(svgPath(moonPath(moon.illum, moon.waxing),
                                    'w-moon-lit'));
        }
        wrap.appendChild(svg);
        const pct = formatPercent(moon.illum);
        if (pct) {
            const text = el('span', null, 'w-moon-pct');
            text.textContent = pct;
            wrap.appendChild(text);
        }
        return wrap;
    }

    function renderGlyph(name, label) {
        const svg = svgIcon(GLYPHS[name], 'w-glyph');
        if (svg && label) {
            svg.removeAttribute('aria-hidden');
            svg.setAttribute('role', 'img');
            svg.setAttribute('aria-label', label);
        }
        return svg;
    }

    // The battery icon, with its charge drawn inside it (T6.10).
    //
    // The bar is the one place this set departs from the weather glyphs, and
    // it is the reason the icon is worth more than the word it replaced: a
    // filled outline is read before a two-digit number is, from the distance
    // this panel is actually looked at. It says the same thing the number
    // says, which is exactly what the sparkline does beside a price.
    //
    // **The gap is the second cut, and it is the whole of the fix.** The bar
    // used to run to the outline's inner edge, so above about 60% it met the
    // outline and the icon became one solid lozenge -- which is what got it
    // reported as unreadable from the chair. It is inset on every side now, so
    // there is always a line of unlit ground between the charge and the wall
    // holding it, at 1% and at 100% alike. That gap is what makes the shape a
    // container with something in it rather than a filled pill.
    //
    // Clamped, because a level over 100 arrives from a phone that has just
    // been plugged in and a bar sticking out of its own battery looks like a
    // rendering bug rather than a full charge.
    function renderBatteryIcon(level) {
        const svg = svgIcon(ICONS.battery, 'b-icon');
        if (!svg) {
            return null;
        }
        // The terminal, drawn rather than stroked: a nub is what a battery is
        // recognised by, and a 2.8-unit hairline standing a pixel and a half
        // off the body was invisible at this size.
        svg.appendChild(svgPath(ICONS.batteryCap, 'b-solid'));

        const fraction = Math.max(0, Math.min(1, level / 100));
        if (fraction > 0) {
            // The body's inner edge is not the path's coordinates -- a
            // 1.8-unit stroke sits half outside the line it is drawn on --
            // and the gap comes off that again. Inside runs 4.5..14.5 across
            // and 10.3..13.7 down.
            svg.appendChild(svgRect(4.5, 10.3,
                                    Math.round(10 * fraction * 100) / 100,
                                    3.4, 0.6, 'b-fill'));
        }
        return svg;
    }

    // The thermometer (T6.10): an outline, a filled bulb and column, and a
    // scale down one side. The fill is what says mercury and the scale is
    // what says instrument -- without either, an outline this size is a
    // keyhole or a lowercase i, which is what the first cut was read as.
    function renderThermometerIcon() {
        const svg = svgIcon(ICONS.thermometer, 'b-icon');
        if (!svg) {
            return null;
        }
        svg.appendChild(svgRect(11.2, 7.5, 1.6, 8.5, 0.8, 'b-solid'));
        const bulb = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        bulb.setAttribute('cx', '12');
        bulb.setAttribute('cy', '16.6');
        bulb.setAttribute('r', '2.5');
        bulb.setAttribute('class', 'b-solid');
        svg.appendChild(bulb);
        for (const d of ICONS.thermometerTicks) {
            svg.appendChild(svgPath(d, null));
        }
        return svg;
    }

    // Three lines where T6.8 made four and T6.3 found one (T6.12). The card is
    // half the height it was -- the column it lives in is two cards deep now --
    // and the line that went is the one the glyph was already drawing: the
    // condition.
    //
    // The order is the order it gets read in -- where, how warm, between what
    // -- and only the second of those is large. The glyph sits beside the
    // temperature rather than above the city because the two of them are the
    // glance: 23 degrees and a cloud.
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

        // The city, and the day's chance of rain at the other end of its line
        // (T6.15). Asked for from the chair: a drop and a number, no word, and
        // right-aligned so it sits directly above the moon's percentage -- the
        // two are the card's only two percentages and they read as a column.
        const city = el('div', null, 'w-city');
        const chance = chanceOfRain(weather);
        if (chance !== null) {
            const rain = el('div', null, 'w-chance');
            // The `rain` glyph: a cloud with rain under it, the same shape
            // the sky's own glyph uses for a rainy code.
            //
            // The first cut was a single filled drop, and it was reported from
            // the chair: "gota fica parecendo umidade". Correct -- a drop on
            // its own is what a hygrometer draws, and this number is about the
            // sky. Reusing the set's rain shape also means the card says rain
            // the same way twice rather than inventing a second vocabulary.
            const drop = svgIcon(GLYPHS.rain, 'w-chance-glyph');
            if (drop) {
                drop.setAttribute('role', 'img');
                // The one word in this, and it is not drawn: the icon is a
                // shape and a reader that speaks the DOM aloud needs to be
                // told it is about rain. Same split as the weather glyph.
                drop.setAttribute('aria-label', words.rainChance);
                drop.removeAttribute('aria-hidden');
                rain.appendChild(drop);
            }
            const pct = el('span', null, 'w-chance-pct');
            pct.textContent = formatPercent(chance);
            rain.appendChild(pct);
            city.appendChild(rain);
        }
        // After the float and not before it: a float only pushes the inline
        // content that follows it in the DOM, so the city has to come second
        // or it would be laid out first and the drop would drop below it.
        city.appendChild(document.createTextNode(weather.city));

        const temp = el('div', null, 'w-temp');
        temp.textContent = `${formatTemp(weather.tempC)}°C`;
        // The only value outside the lists worth a pulse. It is the second
        // largest number on the panel and the server refreshes it on its own
        // clock, so it can change on a cycle where nothing else did -- which is
        // exactly the case a reader would otherwise miss.
        pulseIfChanged(temp, before);
        const main = el('div', null, 'w-main');
        // The condition, as a picture when there is one and as the word when
        // there is not.
        //
        // The second half is not a nicety and was found by the review of
        // T6.12. `weatherGlyph` answers 'unknown' for any WMO code the set
        // does not draw -- 56, 57, 66, 67, 77, 85 and 86 are all real
        // open-meteo values, and the server forwards the raw code -- GLYPHS
        // has no 'unknown' entry, so `renderGlyph` returns null and the label
        // computed for it went nowhere. The card then said `3°C 1° / 5°` about
        // freezing rain and nothing at all about the freezing. `.w-cond` used
        // to carry that word; deleting the line deleted the fallback with it.
        //
        // In the glyph's own slot rather than on a line of its own, because a
        // line of its own is the 33px this card no longer has (see the budget
        // in theme.css). Two lines of 20px text is 48px against the
        // temperature's 48.4 -- 44px at line-height 1.1, since T6.12 -- so the
        // row does not grow, verified in the harness with an unmapped code at
        // 872x392. The margin is 0.4px, not the 4px an earlier draft of this
        // comment claimed by quoting the old 48px type: nudge either number
        // and this stops being true, so measure rather than assume.
        const label = words.weather[weather.code] || words.unknown;
        const glyph = renderGlyph(weatherGlyph(weather.code, weather.isDay), label);
        if (glyph) {
            main.append(glyph, temp);
        } else {
            const named = el('div', null, 'w-label');
            named.textContent = label;
            main.append(named, temp);
        }

        // The min/max and the moon share a line, and it is the one line on this
        // card with width to spare: `18.3 / 28.5` is about half of the 204px
        // interior. The moon therefore costs the card no height, which matters
        // because T6.12 left it 6.6px of slack (the budget is in theme.css).
        const range = el('div', null, 'w-range');
        const span = el('span', null, 'w-range-temps');
        span.textContent = formatRange(weather.minC, weather.maxC);
        range.appendChild(span);
        const moon = renderMoon(moonFields(weather.moon, words));
        if (moon) {
            range.appendChild(moon);
        }

        body.append(city, main, range);
        els.weather.appendChild(body);
    }

    // The AGENDA card's three pictures, as stroke paths on a 24-unit grid.
    // Names come from agendaRows; what they look like is this theme's. A
    // name this table does not know draws nothing, like an unknown weather
    // glyph: the row's words still say what it is.
    const AGENDA_ICONS = {
        live: 'M8 5.5v13l10-6.5z',
        clock: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 7v5l3 2',
        calendar: 'M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1M4 10h16M9 3v4M15 3v4',
    };

    function agendaIcon(name) {
        const d = AGENDA_ICONS[name];
        if (!d) {
            return null;
        }
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', `a-icon a-icon-${name}`);
        svg.setAttribute('viewBox', '0 0 24 24');
        // Decoration, like the sparklines: the row's words carry the meaning.
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        svg.appendChild(path);
        return svg;
    }

    // Ten segments, filled by how far through the meeting the clock is.
    // Segments rather than a smooth bar: at a redraw a minute the bar moves
    // in steps anyway, and a HUD's segments say so honestly. No animation --
    // at night the panel keeps still, and a bar that only ever grows needs none.
    const AGENDA_SEGMENTS = 10;

    function agendaBar(progress) {
        const bar = el('div', null, 'a-bar');
        const lit = agendaSegments(progress, AGENDA_SEGMENTS);
        for (let i = 0; i < AGENDA_SEGMENTS; i += 1) {
            bar.appendChild(el('i', null, i < lit ? 'on' : null));
        }
        return bar;
    }

    // The chip for a meeting in progress, the icon otherwise. The word rather
    // than a colour alone: a chip says "now" to anybody, and a screen reader
    // reads it -- on either row.
    function agendaMark(row) {
        if (row.live) {
            const chip = el('span', null, 'a-chip');
            chip.textContent = words.agenda.now.toUpperCase();
            return chip;
        }
        return agendaIcon(row.icon);
    }

    // The AGENDA card (T9.1), a quest tracker since the redesign: the first
    // event is read from the chair -- a head line, its title and, while it
    // runs, a segmented bar -- and up to two more under it: the second on two
    // lines, the third on one, or both on one beside a failure line. No
    // payload agenda, or a PC with no calendar connected, puts the card back
    // to reserved: empty, titled, and marked for e2e/layout/measure.js. A
    // failed account costs its own line and nothing else.
    //
    // The first row: a head line (the mark, when, and what is left), the
    // title, and the bar while the meeting runs.
    function agendaLead(row) {
        const lead = el('div', null, 'a-lead' + (row.live ? ' a-live' : ''));
        const head = el('div', null, 'a-head');
        const mark = agendaMark(row);
        if (mark) {
            head.appendChild(mark);
        }
        const when = el('span', null, 'a-when');
        when.textContent = row.when;
        head.appendChild(when);
        if (row.aside) {
            const aside = el('span', null, 'a-aside');
            aside.textContent = row.aside;
            head.appendChild(aside);
        }
        lead.appendChild(head);
        const title = el('div', null, 'a-title');
        title.textContent = row.title;
        // The whole title for a reader that speaks the DOM; the line ellipsises.
        title.title = row.title;
        lead.appendChild(title);
        if (row.progress !== null) {
            lead.appendChild(agendaBar(row.progress));
        }
        return lead;
    }

    // The second row, when there is room for it to be two lines: the mark and
    // when, then the title on a line of its own -- the full width of the
    // card, which is what a title needs and a single shared line never gave
    // it ("amanhã 09:00 · exame ...").
    function agendaStacked(row) {
        const next = el('div', null, 'a-next a-stacked' + (row.live ? ' a-live' : ''));
        const head = el('div', null, 'a-sub');
        const mark = agendaMark(row);
        if (mark) {
            head.appendChild(mark);
        }
        const when = el('span', null, 'a-when');
        when.textContent = row.when;
        head.appendChild(when);
        const title = el('div', null, 'a-title');
        title.textContent = row.title;
        title.title = row.title;
        next.append(head, title);
        return next;
    }

    // A later row: one line, icon, when, title.
    function agendaNext(row) {
        const next = el('div', null, 'a-next' + (row.live ? ' a-live' : ''));
        const mark = agendaMark(row);
        if (mark) {
            next.appendChild(mark);
        }
        const when = el('span', null, 'a-when');
        when.textContent = row.when;
        const title = el('span', null, 'a-title');
        title.textContent = row.title;
        title.title = row.title;
        next.append(when, title);
        return next;
    }

    function renderAgenda(now) {
        agendaMinute = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
        const card = agendaRows(agenda, now, words.tag);
        els.agenda.textContent = '';
        if (!card) {
            els.agenda.setAttribute('data-reserved', '');
            return;
        }
        els.agenda.removeAttribute('data-reserved');
        const body = el('div', null, 'a-body');
        // Three events: the first in full, the second on two lines, the third
        // on one. A failure line takes two lines of its own, so with one the
        // card keeps two events, both compact -- measured, the three rows and
        // a failure do not fit the ~142px under the title.
        const rows = card.failed ? card.rows.slice(0, 2) : card.rows;
        rows.forEach((row, i) => {
            if (i === 0) {
                body.appendChild(agendaLead(row));
            } else if (i === 1 && !card.failed) {
                body.appendChild(agendaStacked(row));
            } else {
                body.appendChild(agendaNext(row));
            }
        });
        if (card.none) {
            const none = el('div', null, 'a-none');
            none.textContent = card.none;
            body.appendChild(none);
        }
        if (card.failed) {
            const failed = el('div', null, 'a-failed');
            failed.textContent = card.failed;
            body.appendChild(failed);
        }
        els.agenda.appendChild(body);
    }

    // The one diagnostic on a panel of content, so it is a line rather than a
    // card (T5.4 step 3): no title, no border, and nothing until there is
    // something to say. An empty string leaves the space genuinely empty, which
    // is what the panel should look like before the first battery broadcast
    // arrives.
    //
    // Under the date since T6.12, where it used to be the weather card's foot.
    // Nothing in this function changed with it -- the line is built the same
    // way and says the same things -- but the two temperatures it used to sit
    // beside are a card away now, which is the whole reason it moved.
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
            line.append(...[renderThermometerIcon()].filter(Boolean), temp);
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
            agenda: els.agenda,
        });
        els.stale.textContent = words.stale;
        if (!payload) {
            return;
        }
        // The CLOSED label beside the B3 title, first so a card that throws
        // further down cannot leave the previous payload's answer showing.
        els.closed.textContent = words.marketClosed;
        els.closed.hidden = !marketClosed(payload);
        renderList(els.lists.quotes, payload.quotes || [], 'symbol', 'price', 'BRL');
        renderList(els.lists.fx, payload.fx || [], 'pair', 'rate', 'BRL',
                   formatRate, formatPair);
        renderList(els.lists.crypto, payload.crypto || [], 'symbol', 'price', 'USD');
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
        // HH:MM:SS exactly: MainActivity logs this string as evidence the page
        // rendered, and e2e/layout/measure.js asserts its shape.
        els.clock.textContent = `${hours}:${minutes}:${seconds}`;

        // Only when the minute turns: the countdown has minute resolution and
        // rebuilding the card every second would repaint a glowing box sixty
        // times for one change.
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
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
    }

    window.DeskPanel.defineTheme('neon', { render, tick });
})();
