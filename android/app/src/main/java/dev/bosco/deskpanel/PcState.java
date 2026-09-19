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
