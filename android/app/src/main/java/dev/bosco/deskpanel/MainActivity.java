package dev.bosco.deskpanel;

import android.app.Activity;
import android.os.Bundle;
import android.widget.FrameLayout;

/**
 * Proves the toolchain, not the product (T2.1). The WebView arrives in T2.2.
 */
public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(new FrameLayout(this));
    }
}
