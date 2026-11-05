package dev.bosco.deskpanel;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Starts {@link PanelService} after the phone boots (T4.14, ADR 0025).
 *
 * <p>The service, not the Activity: the service is what watches the PC, and
 * it brings the panel up itself when the PC answers, the same way a watchdog
 * revival does. A dark phone with the PC away is the right state after a boot.
 *
 * <p>Starting a foreground service from {@code BOOT_COMPLETED} is one of
 * Android 12's documented exemptions from the background-start restrictions.
 * MIUI delivers the broadcast only to apps on its Autostart list
 * (INSTALL-PHONE step 1); that list allows the start, it does not make one.
 */
public final class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        // Checked, though the manifest filters for it: a receiver that starts
        // a service on any intent is one an adb broadcast can misuse.
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            PanelService.startAtBoot(context);
        }
    }
}
