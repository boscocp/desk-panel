package dev.bosco.deskpanel;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.WindowManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
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
 * keeps web/js/mock.js inert on the device, since the mock loader in
 * index.html only fires under the file: protocol.
 */
public class MainActivity extends Activity implements PanelService.Panel {

    /**
     * The virtual https origin WebViewAssetLoader answers for. /assets/ maps
     * onto the APK's assets, which build.gradle.kts points straight at web/.
     */
    private static final String PANEL_URL =
            "https://appassets.androidplatform.net/assets/index.html";

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
            }
        });

        WebSettings settings = webView.getSettings();
        // The panel's clock is JavaScript; the data it renders will arrive from
        // native Java, never from a fetch inside the page (ADR 0002).
        settings.setJavaScriptEnabled(true);
        // Nothing legitimate in this app loads http:// into the page, so the
        // strictest mode is free. Never widen this to ALWAYS_ALLOW.
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

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
     * <p>{@code screenBrightness} is deliberately left alone, at the window
     * default of {@code -1f}. Dimming to zero was the original design and is
     * now the documented fallback, to be reinstated only if MIUI proves it will
     * not wake the screen (T4.4, ADR 0005).
     */
    @Override
    public void onPcState(boolean online, boolean logTransition) {
        lastOnline = online;
        pushPcStateToPage();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            // Paired with the state rather than latched on. Both are sticky
            // window properties, so leaving them true after going offline would
            // mean that any later resume of this Activity with the PC off — the
            // MIUI relaunch, a notification tap — turned the screen on and
            // showed the panel over the keyguard, with nobody logged in.
            setShowWhenLocked(online);
            setTurnScreenOn(online);
        }
        setKeepScreenOn(online);

        if (logTransition) {
            Log.i(Markers.TAG, Markers.screen(online));
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
     * The one place that touches {@code FLAG_KEEP_SCREEN_ON}. Online, the panel
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
