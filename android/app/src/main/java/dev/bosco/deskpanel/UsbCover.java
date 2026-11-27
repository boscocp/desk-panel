package dev.bosco.deskpanel;

/**
 * Whether the panel was covered by MIUI's USB chooser rather than by a person
 * (T4.15).
 *
 * <p>Reported from the chair on 2026-11-26: every move of the USB switch asks
 * on the phone what the USB connection is for. MIUI's Settings opens
 * {@code UsbModeChooserActivity} on every {@code USB_STATE} with
 * {@code configured=true}, but only while the keyguard is unlocked, and an
 * online panel holds the screen on, so once the phone has been unlocked it
 * stays unlocked all day. All twelve choosers the log kept from 2026-11-25
 * and 2026-11-26 resumed with {@code isKeyguardLocked=false}. The chooser then covers the
 * panel until the screen times out behind it and T4.11 brings the panel back,
 * a minute later.
 *
 * <p>The app cannot see which activity covered it. It can see when it was
 * covered and when USB was configured, and a cover within {@link #WINDOW_MS}
 * of a USB connect is the chooser. The chooser opened 13 ms after the
 * broadcast on 2026-11-26 at 09:02:06. A person opening an app the same
 * moment the cable is replugged is the only false positive, and what it
 * costs them is one tap back.
 *
 * <p>Plain Java, no Android imports, so the decision is covered on the JVM.
 */
public final class UsbCover {

    /**
     * How far apart the cover and the USB connect may be. Either can arrive
     * first: the broadcast reaches this app and MIUI's Settings independently.
     */
    public static final long WINDOW_MS = 5_000L;

    private UsbCover() {
    }

    /**
     * Whether to raise the panel over what just covered it.
     *
     * @param online    the PC's last verdict was ONLINE; offline, nothing holds
     *                  the screen and there is no panel to give back
     * @param coveredAt {@code elapsedRealtime} of the panel's stop while
     *                  interactive, or 0 if it is not covered
     * @param usbAt     {@code elapsedRealtime} of the last USB connect, or 0
     *                  if none was seen
     */
    public static boolean reclaim(boolean online, long coveredAt, long usbAt) {
        if (!online || coveredAt <= 0 || usbAt <= 0) {
            return false;
        }
        return Math.abs(coveredAt - usbAt) <= WINDOW_MS;
    }
}
