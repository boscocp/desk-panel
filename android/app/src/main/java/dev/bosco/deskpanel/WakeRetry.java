package dev.bosco.deskpanel;

/**
 * What to do about a wake that has not shown the panel yet (T4.11, ADR 0024).
 *
 * <p>{@code startActivity} only queues the request, and Android 12 may drop it
 * without telling the app: measured 2026-10-23, when the panel lost "Display
 * over other apps" and a login at 13:35:23 logged {@code state=online} and
 * {@code screen=wake} while the system logged {@code Background activity start
 * [... inVisibleTask: false]} and the phone stayed dozing with every ping
 * answering. Nothing asked again, so the panel stayed dark until a hand pressed
 * the power key.
 *
 * <p>So {@code PanelService} checks back {@link #RETRY_MS} after each request
 * and asks this class what the state of things means. Plain Java, no Android
 * imports, so the decision is covered on the JVM; the service supplies the
 * facts and acts on the answer.
 */
public final class WakeRetry {

    /**
     * How long a requested wake has to light the display before it is asked
     * for again. A successful wake gains focus in well under a second
     * (14:40:24 in wave 48, 12:15:25 on 2026-10-23), so thirty seconds never
     * races a wake that is merely slow, and it caps a refused one at two
     * retries a minute.
     */
    public static final long RETRY_MS = 30_000L;

    /** What the service does when the check comes round. */
    public enum Step {
        /** The PC is no longer online: nothing should be lit, stop checking. */
        STOP,
        /** The display is on: the wake landed, or a person has the phone. */
        SETTLED,
        /** The PC is online and the display is dark: ask again. */
        RETRY
    }

    private WakeRetry() {
    }

    /**
     * The check, {@link #RETRY_MS} after a request.
     *
     * <p>Only a dark display is retried. A lit one is settled whoever is in
     * front: either the panel came up, or somebody turned the screen on and is
     * using the phone, and pulling the panel over their app every thirty
     * seconds is not what a wake is for (found by review).
     *
     * @param online      the PC's last verdict was ONLINE
     * @param interactive the display is on ({@code PowerManager.isInteractive})
     */
    public static Step next(boolean online, boolean interactive) {
        if (!online) {
            return Step.STOP;
        }
        return interactive ? Step.SETTLED : Step.RETRY;
    }

    /**
     * Whether the panel is up on a lit display already, so a request has
     * nothing to wait for. Both, because each alone lies: a window keeps focus
     * while the display dozes under it, and a lit display may be showing
     * another app.
     */
    public static boolean showing(boolean focused, boolean interactive) {
        return focused && interactive;
    }
}
