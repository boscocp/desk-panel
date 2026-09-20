// The core's only contact with the DOM.
//
// T6.7 moved the boundary between core and theme. It used to separate colour
// from everything else: the palette was themeable and the markup was not, so a
// theme that wanted the change above the price had to edit the file holding
// window.onData. It now separates presentation from data, and this file is the
// seam.
//
// Above it, js/app.js: the native bridge, the payload, the clock's timing, the
// screen state. Not one element, id or class name.
// Below it, web/themes/<name>/: every element on the panel.
// Here: the document itself -- which stylesheet is live, which theme object is
// current, what the theme's root element is, and the blackout attribute.
//
// Deliberately not a plugin system. There is one consumer and it is a page
// that renders a payload, so a theme is an object with two functions and a
// stylesheet, and this file is the whole of the machinery (T6.7 notes).

(function () {
    'use strict';

    // The theme that ships with the panel, and the one anything unrecognised
    // falls back to. A panel that renders nothing because of a typo in a file
    // on the PC is the worst failure available here (T6.7 step 4).
    const FALLBACK = 'neon';

    const themes = {};
    let current = null;      // the theme object in force
    let currentName = null;  // its name, so a repeat select() is a no-op
    // The unknown-theme line is said once per *name*, not once per process. A
    // bare boolean was the first cut and it loses the second typo: fix "nen" to
    // "plain", mistype it as "plian" months later, and the panel falls back in
    // silence while config.example.toml still promises the mistake costs a look
    // in logcat. Keyed on the name, the warning is still not repeated every 60s
    // -- useTheme returns early once the fallback is current -- and a *new*
    // wrong name is still reported.
    let warnedFor = null;

    // document.body, and that is the whole of the theme's territory. The
    // scripts live in <head> with defer, so the body a theme is handed is
    // empty on the first render and holds only what the theme put there on
    // every one after.
    function root() {
        return document.body;
    }

    // index.html carries every packaged theme's stylesheet, all but one
    // switched off with media="not all". Switching is therefore a property
    // change on links the browser has already fetched -- no request, no frame
    // of unstyled panel on a theme swap.
    //
    // `media` rather than the `disabled` property: disabled was dropped from
    // the HTML spec and a browser that ignored it would apply *both* themes'
    // rules at once, which breaks the default look to make a non-default one
    // work. A media query that matches nothing is not optional.
    function applyStylesheet(name) {
        const links = document.querySelectorAll('link[rel="stylesheet"][data-theme]');
        for (const link of links) {
            link.media = link.dataset.theme === name ? 'all' : 'not all';
        }
    }

    // Called by each web/themes/<name>/theme.js as it parses. Registration is
    // static -- index.html loads every packaged theme's script with defer --
    // because #clock has to exist before onPageFinished reads it for the
    // panel=rendered marker (MainActivity, ADR 0009). An injected <script>
    // would run after that, and the marker would report an empty clock on a
    // panel that was about to be perfectly fine.
    function defineTheme(name, api) {
        themes[name] = api;
    }

    // Returns true if the live theme changed, so the caller knows a full
    // re-render is due.
    function useTheme(name) {
        let wanted = name || FALLBACK;
        if (!themes[wanted]) {
            if (warnedFor !== wanted) {
                // Reaches logcat through Chromium's own console bridge; there
                // is no WebChromeClient and this is not worth adding one for.
                console.warn('desk-panel: no theme "' + wanted + '" is packaged; '
                             + 'falling back to "' + FALLBACK + '"');
                warnedFor = wanted;
            }
            wanted = FALLBACK;
        }
        if (wanted === currentName) {
            return false;
        }
        // The outgoing theme's markup is not the incoming one's to inherit,
        // and a theme is entitled to assume an empty root on its first render.
        root().textContent = '';
        current = themes[wanted];
        currentName = wanted;
        applyStylesheet(wanted);
        return true;
    }

    // The two calls the boundary is made of. Both are guarded rather than
    // asserted: a theme whose render() throws must not take the clock down
    // with it, because a panel showing a stale card is worth more than a
    // panel showing nothing.
    function render(payload) {
        if (!current) {
            return;
        }
        try {
            current.render(payload, root());
        } catch (err) {
            console.error('desk-panel: theme "' + currentName + '" render failed', err);
        }
    }

    function tick(now) {
        if (!current) {
            return;
        }
        try {
            current.tick(now, root());
        } catch (err) {
            console.error('desk-panel: theme "' + currentName + '" tick failed', err);
        }
    }

    // One attribute on <html>, and css/style.css owns what it means. Not a
    // class on <body>, because <body> belongs to the theme and a theme that
    // cleared it would clear the blackout with it.
    function blackout(dark) {
        if (dark) {
            document.documentElement.setAttribute('data-panel', 'dark');
        } else {
            document.documentElement.removeAttribute('data-panel');
        }
    }

    window.DeskPanel = {
        defineTheme: defineTheme,
        useTheme: useTheme,
        render: render,
        tick: tick,
        blackout: blackout,
    };
})();
