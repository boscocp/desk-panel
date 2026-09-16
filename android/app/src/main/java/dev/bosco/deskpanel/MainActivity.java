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
public class MainActivity extends Activity {

    private static final String TAG = "DeskPanel";

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
                        value -> Log.i(TAG, "panel=rendered clock=" + value));
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
        setKeepScreenOn(true);
        enterImmersiveMode();

        webView.loadUrl(PANEL_URL);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        // Transient bars are shown again whenever the window loses and regains
        // focus, so the request has to be repeated rather than made once.
        if (hasFocus) {
            enterImmersiveMode();
        }
    }

    /**
     * The one place that touches {@code FLAG_KEEP_SCREEN_ON}. Online, the panel
     * holds it and the screen never sleeps; T4.4 clears it through this same
     * method so Android's own timeout can put the screen out once the PC is
     * gone. Screen state follows PC state, never a timer of ours (invariant 3),
     * which is why nothing here schedules anything.
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
