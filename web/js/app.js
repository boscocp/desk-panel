// The panel's core. State, timing, and the three calls native Java makes into
// the page -- and nothing else.
//
// There is no element, id or class name anywhere in this file, and that is
// checked (T6.7's acceptance greps for them). Everything the panel looks like
// is in web/themes/<name>/; js/host.js is the seam between the two, and
// docs/THEMING.md is the contract.
//
// Invariant 1: this file never fetches anything. Values arrive from Java
// through window.onData, and there is no other way in (ADR 0002).

(function () {
    'use strict';

    const host = window.DeskPanel;

    // Everything the panel knows. `payload` is null until the first word from
    // the PC, which is a state a theme has to render -- the skeleton and no
    // values -- because the clock is worth showing before the market is.
    let payload = null;
    let online = true;
    let tooHot = false;
    let clockTimer = null;
    // A payload arrived while the panel was dark and has not been drawn.
    let pending = false;

    // Both blackouts mean the same thing to the page: there is nothing worth
    // lighting a pixel for, so there is nothing worth writing to the DOM for
    // either.
    function visible() {
        return online && !tooHot;
    }

    // --- The clock ---------------------------------------------------------
    // Core keeps the time and the schedule; the theme decides what a clock
    // looks like. The Date goes across the boundary rather than a pair of
    // formatted strings, so a theme can show seconds or not, a 24h clock or
    // not, and a date in whatever shape it likes.

    function paintClock() {
        host.tick(new Date());
    }

    // The page's half of the arbitration, and the only place the timer is
    // touched: the clock runs while the panel is actually visible.
    //
    // Nothing is visible under either blackout, so a per-second DOM write is
    // pure cost -- and under the thermal one it is cost paid by a device that
    // is being blanked *because* it is working too hard (ADR 0012), which is
    // the worse of the two bargains. Offline it is cost paid in exactly the
    // state the device holds a wake lock to survive (ADR 0014).
    function applyClock() {
        if (visible() && clockTimer === null) {
            paintClock();
            clockTimer = setInterval(paintClock, 1000);
        } else if (!visible() && clockTimer !== null) {
            clearInterval(clockTimer);
            clockTimer = null;
        }
    }

    // --- The screen --------------------------------------------------------
    // Offline and too-hot are two reasons for one outcome: there is nothing
    // worth lighting a pixel for. host.blackout() puts that on <html> and
    // css/style.css hides the theme's root, so the rule cannot be lost by a
    // theme that forgot it (invariant 3, ADR 0005; T5.5, ADR 0012).

    function applyScreen() {
        host.blackout(!visible());
        // Whatever arrived while nobody could see it, drawn now that somebody
        // can. Before applyClock, so the clock the timer starts painting is
        // already sitting in the markup this payload produced.
        //
        // `resumed`, because this is the one render where the panel's own
        // markup is not evidence of anything: it has been hidden, for a minute
        // under the thermal cutoff or for a night with the PC off, and nothing
        // in it has been seen.
        if (visible() && pending) {
            paintData({ resumed: true });
        }
        applyClock();
    }

    // --- The native bridge -------------------------------------------------
    // Called from Java, and only from Java. In a browser none of the three is
    // ever called except by js/mock.js, which is why the panel's development
    // state is the online one.

    // MainActivity.onPcState, on every transition and only on transitions.
    window.onPcState = (isOnline) => {
        online = !!isOnline;
        applyScreen();
    };

    // MainActivity.onThermal, when the device crosses a thermal threshold and
    // on every page load -- so a reloaded panel is not left painting into a
    // phone that is still too hot (T5.5, ADR 0012). The window's brightness is
    // already at zero by the time this arrives; the blackout is the render
    // that goes with it, for a display whose floor is a dim backlight rather
    // than none.
    window.onThermal = (isTooHot) => {
        tooHot = !!isTooHot;
        applyScreen();
    };

    // Theme selection is runtime config (T3.12): the server's `theme` key rides
    // the payload, so changing the panel's look is editing a file on the PC,
    // never a rebuild. Every packaged theme is already loaded, so a switch
    // costs a re-render and no request.
    //
    // `context` is handed straight to the theme (js/host.js). It says what the
    // theme cannot see for itself: whether this render is the first since the
    // panel was dark. The blackout hides the body rather than emptying it, so
    // a theme comparing what it is about to draw against what it is showing
    // would read values nobody has looked at for twelve hours as "current".
    function paintData(context) {
        host.useTheme(payload && payload.theme);
        host.render(payload, context);
        // Straight after the render, because a theme that rebuilt its clock
        // element would otherwise show an empty one for up to a second -- and
        // on the device the first payload lands within a second of the page
        // load that MainActivity reads #clock from.
        paintClock();
        pending = false;
    }

    // The one entry point for quotes, fx, crypto, weather and battery --
    // native in production, js/mock.js in the browser. Payload shape:
    // tasks/T1.2-mock-fixtures.md. A full replacement, never a patch.
    window.onData = (next) => {
        if (!next) {
            return;
        }
        payload = next;
        // Held, not drawn, while the panel is dark -- the same bargain the
        // clock timer takes, and for the stronger reason. The data poller keeps
        // running under the thermal cutoff, because the Activity stays in the
        // foreground so it can notice the device cooling (T5.5), so without
        // this every cycle would rebuild the whole panel into a hidden DOM on
        // a device that is being blanked *because* it is working too hard
        // (ADR 0012). Offline the poller is paused anyway, so this costs
        // nothing there and is still the honest place for the rule.
        //
        // Nothing is lost: applyScreen draws the held payload the moment the
        // panel comes back, and `payload` is always the latest one.
        if (!visible()) {
            pending = true;
            return;
        }
        paintData();
    };

    // --- Start -------------------------------------------------------------
    // Synchronous, while the deferred scripts are still running and before the
    // load event: MainActivity.onPageFinished reads #clock out of the DOM and
    // logs panel=rendered clock=HH:MM:SS, which is the app's own evidence that
    // the asset pipeline, the https origin, JavaScript and the DOM all worked
    // (T2.2, ADR 0009). A panel whose first paint waited for a payload would
    // report an empty clock, and would show nothing at all on a PC whose
    // server is up but whose upstreams are down.
    // The skeleton and the clock are painted unconditionally, before the screen
    // state is known: a page that loads while the device is still too hot must
    // not report an empty clock, and onThermal(true) arrives on every page load
    // for exactly that reason (T5.5). This is once per page, not once a cycle,
    // so the rule onData takes below does not apply to it.
    host.useTheme(null);
    host.render(payload);
    paintClock();
    applyScreen();
})();
