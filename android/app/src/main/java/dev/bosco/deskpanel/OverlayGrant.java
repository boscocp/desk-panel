package dev.bosco.deskpanel;

/**
 * Whether "Display over other apps" has just been lost or given back (T4.15,
 * ADR 0026).
 *
 * <p>The grant is what lets a service revived by the watchdog raise the panel
 * (ADR 0023). It has gone from {@code allow} to {@code ignore} on this phone
 * five times with no install near it, and every time the first sign
 * was a dark morning: on 2026-11-16 a WebView update killed the app at 15:49,
 * the watchdog revived the service at 16:19, and every {@code state=online}
 * after that, through two logins at the PC and one at the Mac, left the
 * screen off. The grant had been in use on 11-06 and was refused on 11-16,
 * and nothing on the phone records the change in between.
 *
 * <p>So {@code PanelService} reads the grant whenever it might have moved and
 * asks this class whether the reading is news. Plain Java, no Android
 * imports, so the rule is covered on the JVM.
 */
public final class OverlayGrant {

    /** What a reading means against the one before it. */
    public enum Change {
        /** Nothing worth a line. */
        NONE,
        /** The grant is missing, and it was there or nobody had looked yet. */
        LOST,
        /** The grant is back after a reading that found it missing. */
        BACK
    }

    private OverlayGrant() {
    }

    /**
     * @param before the previous reading, or null before the first one
     * @param now    whether the grant is held now
     * @return {@link Change#LOST} on the first reading that finds it missing,
     *         including the very first, because a service that starts without
     *         it is the case that matters (the watchdog revival);
     *         {@link Change#BACK} when it returns; otherwise
     *         {@link Change#NONE}, which is also a first reading that finds
     *         it held -- that is the resting state, and a line every start
     *         would bury the one that is not
     */
    public static Change change(Boolean before, boolean now) {
        if (!now) {
            return Boolean.FALSE.equals(before) ? Change.NONE : Change.LOST;
        }
        return Boolean.FALSE.equals(before) ? Change.BACK : Change.NONE;
    }
}
