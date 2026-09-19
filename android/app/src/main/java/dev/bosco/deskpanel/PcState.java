package dev.bosco.deskpanel;

/**
 * The online/offline machine and the polling cadence, as plain Java.
 *
 * <p>No Android imports, deliberately: this is the part worth testing, and
 * {@code ./gradlew test} runs it on the JVM in a second instead of waiting
 * minutes on a device for a backoff ladder to climb. It also reads no clock and
 * starts no threads — every method that cares about time takes it as an
 * argument, so a test can jump forward without sleeping.
 *
 * <p>It decides <em>that</em> a transition happened; it does not log it.
 * Emitting the state markers the E2E suite asserts on stays on the Android side
 * of the boundary, which is the only side that has {@code Log}. Their exact
 * spelling lives in {@link Markers}, once, and nowhere else (TT.6).
 */
public final class PcState {

    /** Which side of the boundary we are on. */
    public enum State {
        /** No probe has completed yet, so neither marker has been earned. */
        UNKNOWN,
        /** The PC answered: a human is logged in. */
        ONLINE,
        /** The PC did not answer: the session is gone, let the screen sleep. */
        OFFLINE
    }

    /** Cadence while the PC answers. */
    public static final long ONLINE_INTERVAL_MS = 2000L;

    /** First offline retry; doubles from here. */
    public static final long BACKOFF_BASE_MS = 2000L;

    /**
     * Ceiling on the offline retry. The phone is on battery whenever the PC is
     * off (see DEVICE-CARE.md), so the ladder stops climbing here rather than
     * running away, and still notices a login within 15s.
     */
    public static final long BACKOFF_CAP_MS = 15000L;

    /**
     * The sparse offline probe, for when the phone is offline <em>and</em> on
     * its own battery (T5.6). This is not a rung on the ladder above: it is
     * what replaces the ladder entirely, because in that state there is no
     * in-process schedule at all — the device is allowed to suspend and
     * {@code AlarmManager} owns the next probe.
     *
     * <p>15 minutes rather than something responsive, and the number is the
     * platform's, not a preference. Doze clamps an allow-while-idle alarm to
     * roughly nine minutes, so anything tighter is a promise that would not be
     * kept. It can afford to be this sparse because it is a <em>backstop</em>:
     * with the USB dying with the PC, power returning is the real signal and
     * arrives as {@code ACTION_POWER_CONNECTED} the instant the PC comes back
     * (ADR 0014).
     */
    public static final long DORMANT_ALARM_MS = 15 * 60 * 1000L;

    private State state = State.UNKNOWN;
    private boolean transitioned;
    private int consecutiveFailures;
    private boolean probed;
    private long lastProbeAtMs;

    /**
     * Feeds one probe result in.
     *
     * @param reachable whether the PC server answered
     * @param nowMs     the time of the probe, in milliseconds on any monotonic
     *                  scale the caller likes
     * @return true if this result changed the state — i.e. exactly the polls on
     *         which a marker should be logged and the screen retoggled
     */
    public boolean record(boolean reachable, long nowMs) {
        probed = true;
        lastProbeAtMs = nowMs;

        if (reachable) {
            consecutiveFailures = 0;
        } else if (consecutiveFailures < Integer.MAX_VALUE) {
            consecutiveFailures++;
        }

        State next = reachable ? State.ONLINE : State.OFFLINE;
        transitioned = next != state;
        state = next;
        return transitioned;
    }

    /** The current state. */
    public State state() {
        return state;
    }

    /** Whether the PC answered the last probe. */
    public boolean isOnline() {
        return state == State.ONLINE;
    }

    /**
     * Whether the most recent {@link #record} changed the state. Sticky only
     * until the next probe, so callers that log on it log once per transition
     * and not once per poll.
     */
    public boolean transitioned() {
        return transitioned;
    }

    /** Failed probes since the last success. */
    public int consecutiveFailures() {
        return consecutiveFailures;
    }

    /**
     * How long to wait before the next probe: {@value #ONLINE_INTERVAL_MS}ms
     * while online, and 2000, 4000, 8000 … capped at {@value #BACKOFF_CAP_MS}
     * while offline. A success resets the ladder, so recovery is back on the
     * online cadence immediately.
     */
    public long nextIntervalMs() {
        if (consecutiveFailures == 0) {
            return ONLINE_INTERVAL_MS;
        }
        long interval = BACKOFF_BASE_MS;
        for (int i = 1; i < consecutiveFailures && interval < BACKOFF_CAP_MS; i++) {
            interval *= 2;
        }
        return Math.min(interval, BACKOFF_CAP_MS);
    }

    /**
     * Whether the poll schedule should leave this process altogether (T5.6).
     *
     * <p>Dormant is one state and one only: <b>offline and on battery</b>.
     * Offline on mains is the ADR 0014 arrangement and stays exactly as it was
     * — a wake lock and the ladder above, which costs a little heat on a phone
     * that is charging anyway. Offline on battery is the state that ADR 0014
     * says makes its own decision wrong, and the difference is not a cadence
     * but an owner: nothing in this process may hold the CPU awake, so there is
     * no thread to run a ladder on and {@code AlarmManager} has to keep the
     * time instead.
     *
     * <p>Online is never dormant, whatever the power. Somebody is looking at
     * the panel, {@code FLAG_KEEP_SCREEN_ON} is holding the device up for the
     * display's sake, and a 2s probe is the cheapest thing happening.
     *
     * <p>A parameter rather than a field, like the clock that {@link #record}
     * takes: this class holds what it learned from probes, and power is not
     * something a probe can tell it.
     *
     * @param onMains whether the charger is connected — {@code EXTRA_PLUGGED},
     *                never {@code EXTRA_STATUS}, which reports
     *                {@code NOT_CHARGING} for a paused charge on a live cable
     */
    public boolean isDormant(boolean onMains) {
        return state == State.OFFLINE && !onMains;
    }

    /**
     * When the next probe is due, on the same scale as the time passed to
     * {@link #record}. Before the first probe there is nothing to wait for.
     */
    public long nextProbeAtMs() {
        return probed ? lastProbeAtMs + nextIntervalMs() : Long.MIN_VALUE;
    }

    /**
     * Whether a probe is due at {@code nowMs}. This is what keeps the poller
     * stateless: it holds no deadline of its own, it asks.
     */
    public boolean isDue(long nowMs) {
        return !probed || nowMs >= nextProbeAtMs();
    }
}
