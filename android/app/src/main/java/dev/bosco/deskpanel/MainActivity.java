package dev.bosco.deskpanel;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.WindowManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;

import androidx.annotation.NonNull;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;
import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewClientCompat;

/**
 * One Activity, one WebView (T2.2). The panel is served from
 * https://appassets.androidplatform.net/ by WebViewAssetLoader rather than
 * file://: that is what makes the page a secure origin, and it is also what
 * keeps web/js/mock.js inert on the device -- the mock feed returns early
 * unless location.protocol is file:, which it never is here. The guard is at
 * the top of mock.js itself; T6.7 moved it out of index.html, where an inline
 * loader could not be placed in the deferred script order the panel now needs.
 */
public class MainActivity extends Activity implements PanelService.Panel {

    /**
     * The virtual https origin WebViewAssetLoader answers for. /assets/ maps
     * onto the APK's assets, which build.gradle.kts points straight at web/.
     */
    private static final String PANEL_URL =
            "https://appassets.androidplatform.net/assets/index.html";

    /**
     * The backlight the night profile holds (T6.4). A fraction of the
     * device's range, not a nit value: {@code screenBrightness} is 0f to 1f
     * and what that comes out as is the panel's business.
     */
    private static final float NIGHT_BRIGHTNESS = 0.15f;

    /** Reads the clock the panel is supposed to have painted. */
    private static final String READ_CLOCK =
            "(function () {"
            + "  var c = document.getElementById('clock');"
            + "  return c ? c.textContent : '';"
            + "})()";

    private WebView webView;

    /**
     * The PC state this window has been told about, or null before the first
     * word from the service. Kept because the page can outlive a message: the
     * WebView reloads on a wake, and a page that reloaded in its online look
     * while the PC is offline would sit lit behind a sleeping backlight.
     * {@code onPageFinished} pushes this back into every page that loads.
     */
    private Boolean lastOnline;

    /**
     * The thermal verdict this window has been told about (T5.5). Not a
     * {@code Boolean} like {@link #lastOnline}: "no reading yet" and "not too
     * hot" call for the same behaviour here — paint — whereas the PC's two
     * states call for opposite ones, which is why that field has to be able to
     * say "nothing heard yet" and this one does not.
     */
    private boolean tooHot;

    /**
     * The brightness override this window was last asked to hold. Kept rather
     * than read back off the layout params, because the two are not the same
     * question — the window manager may round or clamp a value, and a
     * comparison against what it stored would eventually disagree with what
     * was asked for, which would turn a no-op into a relayout every cycle.
     *
     * <p>Starts at the window default, which is what a freshly created window
     * already holds, so the first call that changes nothing changes nothing.
     */
    private float brightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE;

    /**
     * Whether the night profile is in force (T6.4), from {@link PanelService}.
     * A {@code boolean} rather than a {@code Boolean} for the reason
     * {@link #tooHot} is: "nothing heard yet" and "not night" both mean full
     * brightness, so there is nothing for a third state to say.
     */
    private boolean night;

    /**
     * The last payload handed to the page, for the same reason
     * {@link #lastOnline} is kept: the WebView reloads on a wake, and a
     * reloaded page knows nothing until the next refresh a minute later.
     */
    private String lastPayload;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        final WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        webView = new WebView(this);
        webView.setWebViewClient(new WebViewClientCompat() {
            @Override
            public WebResourceResponse shouldInterceptRequest(
                    @NonNull WebView view, @NonNull WebResourceRequest request) {
                return assetLoader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                // A WebView that renders nothing logs nothing, so "no errors in
                // logcat" is not evidence that anything appeared — a black
                // screen passes that test too. Android offers no documented way
                // to ask the device what is on screen (ADR 0009), so the app
                // answers the question itself, the same way it does for screen
                // state. js/app.js calls updateClock() synchronously as it
                // parses, so by the time the page is finished #clock already
                // holds HH:MM:SS; a time-shaped value here means the asset
                // pipeline, the https origin, JavaScript and the DOM all
                // worked. The E2E suite greps for this marker.
                view.evaluateJavascript(READ_CLOCK,
                        value -> Log.i(Markers.TAG, "panel=rendered clock=" + value));

                // The page defines window.onPcState as it parses, so a state
                // delivered before this point hit nothing — a silent
                // ReferenceError, discarded with the null callback. Since only
                // edges are delivered, the page would never hear about it
                // again. Pushing it here closes that window, and covers the
                // reload the wake causes.
                pushPcStateToPage();
                pushThermalToPage();
                pushDataToPage();
            }
        });

        WebSettings settings = webView.getSettings();
        // The panel's clock is JavaScript; the data it renders will arrive from
        // native Java, never from a fetch inside the page (ADR 0002).
        settings.setJavaScriptEnabled(true);
        // Nothing legitimate in this app loads http:// into the page, so the
        // strictest mode is free. Never widen this to ALWAYS_ALLOW.
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        // The app's first *inbound* bridge (T8.2). onData, onPcState and
        // onThermal all run the other way — Java reaching into the page — and
        // this is the only thing the page can call.
        //
        // addJavascriptInterface exposes this object to every script in the
        // WebView, and that is safe here for one reason worth stating rather
        // than assuming: the WebView loads exactly one URL, served from the
        // APK's own assets over WebViewAssetLoader's virtual https origin, it
        // has no other entry point, and mixed content is refused above — so
        // "every script" is "the scripts in this APK". The moment that stops
        // being true this call is a remote code path, not a convenience.
        //
        // One method taking one string, and the string is not trusted: the
        // interface matches it against Actions.ALLOWED and sends the constant
        // that matched. ADR 0015 made that argument about a request arriving
        // over the LAN; this is the same argument on the other side of the
        // wire.
        webView.addJavascriptInterface(new ActionBridge(), "__actions");

        setContentView(webView);

        // Landscape is pinned in the manifest; the other two halves of "looks
        // like a panel" are set here (T2.3).
        //
        // Held unconditionally at startup, before any probe has completed: the
        // panel has just been launched, so somebody is looking at it. The first
        // transition corrects it, and because nothing has been logged yet that
        // first correction is a real transition rather than a repeat.
        setKeepScreenOn(true);
        enterImmersiveMode();

        webView.loadUrl(PANEL_URL);

        // The poll loop lives in a service, not here: the screen going out
        // stops this Activity, and a loop that stopped with it could never
        // notice the PC coming back (ADR 0014). This registration is the whole
        // of the relationship — the service tells the window what happened, and
        // the window is all this class owns.
        PanelService.setPanel(this);
        PanelService.start(this);
    }

    @Override
    protected void onDestroy() {
        // Cleared first: the service holds this in a static field, and an
        // Activity left in one is a leak. Compare-and-clear rather than a plain
        // null, because a relaunch can create the replacement before this runs
        // — see PanelService.clearPanel.
        PanelService.clearPanel(this);
        // Only when the panel is genuinely going away. A stop for a screen that
        // went out does not reach onDestroy, which is exactly the distinction
        // this task needed. stopIfUnclaimed, not stop, for the same reason the
        // clear above compares first: a replacement may already have started
        // the service, and stopping it then would leave the live window with no
        // poll loop and nothing to say so.
        if (isFinishing()) {
            PanelService.stopIfUnclaimed(this);
        }
        super.onDestroy();
    }

    /**
     * One PC transition, on the main thread, from {@link PanelService}.
     *
     * <p>Both halves of the product happen here. The page is told, so it can
     * black itself out rather than sit lit behind a sleeping backlight; and the
     * window is told, so the screen follows the PC and nothing else — never a
     * timeout of ours (invariant 3).
     *
     * <p>Waking is two calls and an order. {@code setShowWhenLocked} gets the
     * panel past the lock screen, {@code setTurnScreenOn} turns the display on
     * when this Activity is next resumed — which is why the service raises it
     * immediately afterwards. Both are API 27 and neither is deprecated; the
     * old {@code FLAG_TURN_SCREEN_ON} and the {@code ACQUIRE_CAUSES_WAKEUP}
     * wake locks are, and are not used here (ADR 0005).
     *
     * <p>{@code screenBrightness} stays at the window default for this
     * transition. T4.4 proved MIUI honours {@code setTurnScreenOn}, so the PC's
     * authority keeps real sleep as its mechanism; brightness zero is the
     * thermal authority's, and it is applied in {@link #applyScreenState()}
     * (T5.5, ADR 0012).
     */
    @Override
    public void onPcState(boolean online, boolean logTransition) {
        lastOnline = online;
        if (!online) {
            // Dropped here as well as in the service, and the second copy is
            // the one that actually reaches the page: onPageFinished pushes
            // whatever this holds, so a wake after a night offline reloaded
            // the WebView and handed it last night's prices with stale:false.
            // The service clearing its own copy was necessary and not enough.
            lastPayload = null;
        }
        pushPcStateToPage();
        applyScreenState();

        if (logTransition) {
            Log.i(Markers.TAG, Markers.screen(online));
        }
    }

    /**
     * One thermal verdict, on the main thread, from {@link PanelService}
     * (T5.5, ADR 0012).
     *
     * <p>Nothing is logged here, unlike {@link #onPcState}, and nothing is
     * logged anywhere in this class for heat. The thermal marker reports "heat
     * is why the panel is dark", which is a conjunction of this verdict and the
     * PC's — and this window holds only one of the two. {@code PanelService}
     * holds both and emits it there, which also survives the Activity
     * recreation that every wake from doze causes.
     */
    @Override
    public void onThermal(boolean hot) {
        tooHot = hot;
        pushThermalToPage();
        applyScreenState();
    }

    /**
     * The night profile, on the main thread, from {@link PanelService}
     * (T6.4).
     *
     * <p>Nothing is pushed to the page here, which is the one thing that
     * makes this callback look different from the two above it. The page
     * asks {@code isNight} in {@code web/js/format.js} the same question
     * about the same payload and drops its own glow, so what crosses this
     * boundary is only what the page cannot reach: the backlight. See
     * {@link NightWindow} for why two implementations of one predicate is
     * the right number here.
     *
     * <p>Nothing is logged here either, for the reason {@link #onThermal}
     * logs nothing: the marker's claim survives this Activity, and MIUI
     * recreates it on every wake from doze.
     */
    @Override
    public void onNight(boolean isNight) {
        night = isNight;
        applyScreenState();
    }

    /**
     * <b>The arbitration.</b> The one place the two authorities meet, and the
     * one expression that decides whether the panel is lit (ADR 0012): the PC
     * is online <em>and</em> the device is not too hot. Either alone puts it
     * out; both must hold to keep it on.
     *
     * <p>It is one method because two conditionals in two callbacks that happen
     * to agree is how a screen ends up lit in a state nobody wrote down. Both
     * callbacks record their own input and call this; neither touches the
     * window itself.
     *
     * <p><b>The mechanisms are not shared, and that is deliberate.</b> The PC's
     * authority is exercised by releasing {@code FLAG_KEEP_SCREEN_ON} and
     * letting Android take the display — real sleep, woken from outside by the
     * service raising this Activity. Heat's authority is exercised by zeroing
     * the window's brightness with the Activity still foreground, so it keeps
     * receiving the battery broadcast and can bring the panel back <em>by
     * itself</em> when the device cools. Swapping heat onto the sleep mechanism
     * would mean nothing was left running to notice the cooling.
     */
    private void applyScreenState() {
        // The arbitration, and the invariant the two calls below add up to:
        //
        //     the panel is lit  ==  the PC is online && the device is not hot
        //
        // It is enforced as two vetoes rather than as one assignment because a
        // veto is all either authority can express in its own mechanism, and
        // the mechanisms are not interchangeable (see this method's javadoc).
        // Written as a comment rather than as a variable because a variable
        // that nothing reads is not the decision being in one place, it is dead
        // code sitting next to the decision.

        // The PC's veto, and only once the PC has actually been heard from. A
        // thermal reading can arrive first — ACTION_BATTERY_CHANGED is sticky
        // and lands within milliseconds, while the first probe takes up to the
        // connect timeout — and it must not be what latches the keyguard flags
        // on for a state nobody has reported yet.
        if (lastOnline != null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
                // Paired with the state rather than latched on. Both are sticky
                // window properties, so leaving them true after going offline
                // would mean that any later resume of this Activity with the PC
                // off — the MIUI relaunch, a notification tap — turned the
                // screen on and showed the panel over the keyguard, with nobody
                // logged in.
                setShowWhenLocked(lastOnline);
                setTurnScreenOn(lastOnline);
            }
            setKeepScreenOn(lastOnline);
        }

        // Heat's veto, and it does not consult the PC. ADR 0012 says either
        // condition alone puts the panel out and both must hold to keep it on,
        // so a device that crossed 45 while the PC was away must still be
        // blanked when the PC comes back — the login turns the display on, and
        // it has to come up dark. Making this one conditional on `online` was
        // the first cut, and it handed exactly that morning a lit panel on a
        // phone at 46 degrees. Nothing is stranded by the stricter version: the
        // receiver is service-scoped, so the verdict keeps updating with the
        // Activity destroyed and the screen out, and cooling clears the
        // override on its own.
        //
        // One call, and it settles the night profile in the same breath
        // (T6.4): both are the same mechanism, so they cannot be two vetoes
        // the way the block above and this one are. applyBrightness holds the
        // precedence between them.
        applyBrightness();
    }

    @Override
    public void onData(String json) {
        lastPayload = json;
        pushDataToPage();
    }

    /**
     * Hands the last payload to the page. The one place data enters the
     * WebView — and it enters from native Java, never from a fetch inside the
     * page (invariant 1, ADR 0002). {@code DataPayload} has already made the
     * string safe to interpolate.
     */
    private void pushDataToPage() {
        if (lastPayload != null) {
            webView.evaluateJavascript("window.onData(" + lastPayload + ")", null);
        }
    }

    /**
     * Hands one shortcut's outcome back to the page (T8.2).
     *
     * <p>{@code id} comes from {@link Actions#ALLOWED} and never from the
     * page, so it is a known-safe literal by the time it is interpolated here
     * — which is the same rule {@code DataPayload} enforces for the payload.
     */
    private void pushActionResultToPage(String id, boolean ok) {
        webView.evaluateJavascript(
                "window.onActionResult('" + id + "'," + ok + ")", null);
    }

    /**
     * The one object the page can call. See the {@code addJavascriptInterface}
     * comment in {@code onCreate} for why exposing it is safe, and
     * {@link Actions} for why the id it is handed is not trusted.
     *
     * <p>Every method here runs on a WebView JavaScript thread, never the main
     * thread, which is why nothing in it touches a View directly.
     */
    private final class ActionBridge {

        /**
         * Fires a shortcut. Returns immediately; the outcome arrives at
         * {@code window.onActionResult(id, ok)} later, or not at all if this
         * returned false.
         *
         * @param id an id the page asked for, untrusted
         * @return whether anything was sent — false for an id this app does
         *         not relay, and false while the PC is away, so a button can
         *         say "no" at once instead of waiting for a result that is
         *         never coming
         */
        @JavascriptInterface
        public boolean invoke(String id) {
            return PanelService.invokeAction(id, (resolved, ok) ->
                    runOnUiThread(() -> pushActionResultToPage(resolved, ok)));
        }
    }

    /**
     * Hands the current PC state to the page, if there is one to hand over.
     * Safe to call repeatedly: {@code window.onPcState} only toggles a class
     * and a timer, so a repeat is a no-op rather than a second transition.
     */
    private void pushPcStateToPage() {
        if (lastOnline != null) {
            webView.evaluateJavascript("window.onPcState(" + lastOnline + ")", null);
        }
    }

    /**
     * Hands the thermal verdict to the page, which blacks itself out the way it
     * already does when the PC goes away. Brightness zero is not always zero
     * light — the panel's own black render is what makes the difference on a
     * device whose floor is a dim backlight rather than none (ADR 0005).
     */
    private void pushThermalToPage() {
        webView.evaluateJavascript("window.onThermal(" + tooHot + ")", null);
    }

    /**
     * <b>The one place that touches {@code screenBrightness}</b>, and since
     * T6.4 it arbitrates three values rather than switching between two:
     *
     * <pre>
     *   0f      too hot      the thermal cutoff (T5.5, ADR 0012)
     *   0.15f   night        the night profile (T6.4)
     *   -1f     otherwise    BRIGHTNESS_OVERRIDE_NONE: whatever the system says
     * </pre>
     *
     * <p>Heat wins, and the order is the whole of the decision. Both are
     * expressed in the same mechanism — unlike the PC's authority, which
     * releases {@code FLAG_KEEP_SCREEN_ON} and lets the display actually
     * sleep — so unlike {@link #applyScreenState()} above, this one cannot be
     * two independent vetoes. It has to be a precedence, and it is written as
     * one expression so that there is no second place where it could be
     * written differently. A night that outranked heat would leave a phone at
     * 46 degrees lighting its backlight because the clock said 23:00, which
     * is exactly the trade ADR 0012 refuses.
     *
     * <p>{@code 0.15f} rather than something lower, and it is a floor rather
     * than a preference: this panel is read at about 50cm in a dark room and
     * a backlight below roughly a tenth is a panel you have to lean towards.
     * The page drops its glow at the same time (T6.4 step 3), so the dimming
     * a reader actually sees is the two together.
     *
     * <p>A no-op unless the value actually changes. Every
     * {@code setAttributes} is a round trip to the window manager and a
     * relayout, and this is reached from a broadcast-driven path and from a
     * per-refresh one.
     *
     * <p>It does not log, and neither marker it might be tempted to emit
     * belongs here. Whether the panel <em>looked</em> different is not a
     * question this method can answer — dimming a window whose display is
     * already out changes nothing anybody can see — and both claims are made
     * in {@code PanelService}, which holds the PC's half of each and survives
     * the Activity recreation every wake from doze causes.
     */
    private void applyBrightness() {
        float wanted;
        if (tooHot) {
            wanted = 0f;
        } else if (night) {
            wanted = NIGHT_BRIGHTNESS;
        } else {
            wanted = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE;
        }
        if (wanted == brightness) {
            return;
        }
        brightness = wanted;

        WindowManager.LayoutParams params = getWindow().getAttributes();
        params.screenBrightness = wanted;
        getWindow().setAttributes(params);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        // Transient bars are shown again whenever the window loses and regains
        // focus, so the request has to be repeated rather than made once.
        if (hasFocus) {
            enterImmersiveMode();
            // Focus is the first moment anything can be sure the display is
            // actually on, which is why the service drops its offline wake lock
            // here and not at the startActivity that asked for the wake.
            PanelService.panelVisible();
        }
    }

    /**
     * The one place that touches {@code FLAG_KEEP_SCREEN_ON}, called only from
     * {@link #applyScreenState()}. Online, the panel
     * holds it and the screen never sleeps; offline it is cleared, and Android's
     * own display timeout — the device's, not one of ours — puts the screen out
     * from there. Screen state follows PC state, never a timer of ours
     * (invariant 3), which is why nothing here schedules anything.
     *
     * <p>The consequence is that the panel does not go dark the instant the PC
     * does: it goes dark one system display timeout later. That delay is the
     * device's setting to shorten, not the app's to override.
     *
     * <p>This is the flag the platform recommends; wake locks for keeping a
     * screen awake have been deprecated since API 17.
     */
    private void setKeepScreenOn(boolean on) {
        if (on) {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        } else {
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }
    }

    /**
     * Hides the status and navigation bars. A swipe from an edge brings them
     * back transiently and they retreat on their own, so the panel stays
     * reachable without a permanent strip of Android across it.
     */
    private void enterImmersiveMode() {
        // The WebView draws edge to edge; without this the hidden bars would
        // still reserve their insets and leave two blank margins.
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);

        // Hiding the bars is not enough on a device with a camera cutout: the
        // window still stops short of it and leaves a black strip down one side
        // of the panel — the left, in landscape, since the cutout rides the
        // display's short edge and turns with the window. Letting the window
        // into it costs nothing, because nothing is laid out against that edge.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            WindowManager.LayoutParams params = getWindow().getAttributes();
            params.layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(params);
        }

        WindowInsetsControllerCompat controller =
                WindowCompat.getInsetsController(getWindow(), webView);
        controller.setSystemBarsBehavior(
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
        controller.hide(WindowInsetsCompat.Type.systemBars());
    }
}
