package dev.bosco.deskpanel;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Asks the PC, over and over, the only question the panel needs answered: is a
 * human logged in? The PC server is started by the graphical session and dies
 * with it, so "it answered /ping" and "someone is logged in" are the same fact
 * (invariant 2).
 *
 * <p>This is the thin Android shell around {@link PcState}: it owns the socket
 * and the scheduling, and nothing else. What a result <em>means</em> — online,
 * offline, whether that is a change, how long to wait before asking again —
 * belongs to {@code PcState}, which is plain Java and covered on the JVM.
 *
 * <p>It is also the app's only network code, on purpose. The page in the
 * WebView never calls {@code fetch}: it is served from an https origin, so a
 * request to a {@code http://} LAN address would be mixed content, and native
 * polling sidesteps the problem instead of weakening
 * {@code MIXED_CONTENT_NEVER_ALLOW} (invariant 1, ADR 0002).
 */
public final class PcPoller {

    private static final String TAG = "DeskPanel";

    /** The PC server's port (T3.1). Only the host varies, and only per build. */
    private static final int PORT = 8777;

    /**
     * Connect and read timeout, applied to both ends of the probe.
     *
     * <p>Deliberately shorter than {@link PcState#ONLINE_INTERVAL_MS}: the
     * failure path has to be as prompt as the success path, because switching
     * the screen off when the PC disappears is the whole product. The platform
     * default is measured in tens of seconds, which would let a dead PC look
     * alive for most of a minute. At 1500 ms a probe against a host that has
     * gone away reaches {@code state=offline} within about a second and a half
     * of the poll that was due. There is no DNS to bound — the host is a bare
     * IPv4 address.
     *
     * <p>Note the arithmetic: the two timeouts are applied separately, so the
     * worst case is their sum, 3000 ms, not 1500. A host that completes the
     * handshake and then says nothing — a PC suspended after {@code accept}, a
     * stateful firewall dropping an established flow — costs both. That is one
     * and a half online intervals, so a probe can outlive the poll that should
     * have followed it; {@link #generation} is what keeps that from mattering.
     */
    private static final int TIMEOUT_MS = 1500;

    private final String pingUrl;

    /** The state machine, kept across pause/resume so a stop is not a reset. */
    private final PcState state = new PcState();

    private final Handler main = new Handler(Looper.getMainLooper());

    /** Written on the main thread by start/stop, read by the poller thread. */
    private volatile boolean running;

    /**
     * Bumped by every {@link #start()}. A probe carries the generation it was
     * booked under and abandons itself the moment that stops being the current
     * one, which is the only thing that actually ends a loop: {@code
     * shutdownNow()} interrupts the thread, and blocking socket I/O on Android
     * does not answer an interrupt. A probe already inside {@code
     * getResponseCode()} therefore runs to its timeout and comes back into a
     * process that may have started a second loop in the meantime — worst case
     * while offline, where a probe blocks for the full connect timeout. Without
     * this counter that straggler reads the new {@code running} and the new
     * scheduler, books itself onto them, and the panel polls at twice the rate
     * for the rest of the session, one extra chain per pause/resume. That is
     * the overnight-battery failure this file's own javadoc warns about.
     */
    private volatile int generation;

    /**
     * The state the main thread has actually acted on, as opposed to the one
     * {@link PcState} holds. They differ exactly when a delivery was dropped —
     * {@code stop()} landing between the post and the runnable — and keeping
     * the two apart is what lets the next poll notice and re-deliver. Trusting
     * {@code record()}'s boolean instead would lose that transition for good:
     * it is sticky only until the next probe, and by then {@code PcState} has
     * moved on and will never report the change again.
     */
    private volatile PcState.State delivered = PcState.State.UNKNOWN;

    private volatile ScheduledExecutorService scheduler;

    /**
     * @param host the PC's LAN address; {@code R.string.pc_host}, which the
     *             build substitutes from {@code .env} (ADR 0013). It is the one
     *             host {@code network_security_config.xml} allows in cleartext.
     */
    public PcPoller(String host) {
        this.pingUrl = "http://" + host + ":" + PORT + "/ping";
    }

    /**
     * Begins polling, first probe immediately. Called from {@code onResume};
     * calling it twice is a no-op, so a resume without a matching pause cannot
     * leave two loops running.
     */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        final int booked = ++generation;
        final ScheduledExecutorService owner = Executors.newSingleThreadScheduledExecutor(
                runnable -> {
                    Thread thread = new Thread(runnable, "pc-poller");
                    // A daemon: nothing here should keep the process alive.
                    thread.setDaemon(true);
                    return thread;
                });
        scheduler = owner;
        // The loop carries its own executor rather than reading the field, so a
        // straggler from a previous generation cannot reach this one at all.
        owner.execute(() -> poll(owner, booked));
    }

    /**
     * Stops polling and releases the thread. Called from {@code onPause} — a
     * poller that outlives the Activity is a leak that shows up as an overnight
     * battery complaint rather than as a crash.
     */
    public void stop() {
        if (!running) {
            return;
        }
        running = false;
        generation++;
        ScheduledExecutorService owner = scheduler;
        scheduler = null;
        if (owner != null) {
            owner.shutdownNow();
        }
    }

    /**
     * One probe, on the poller thread, then the next one booked at whatever
     * interval {@code PcState} asks for. Rescheduling from the tail rather than
     * running at a fixed rate is what lets the offline backoff exist at all
     * (ADR 0008): the loop holds no period of its own, it asks after every
     * result.
     */
    private void poll(ScheduledExecutorService owner, int booked) {
        if (isStale(booked)) {
            return;
        }

        String failure = probe();

        // Checked again on the way out, and this one is not belt-and-braces: a
        // probe that outlived its generation must not touch PcState at all.
        // PcState is plain unsynchronised Java, and a straggler writing to it
        // while the current loop reads is a data race on the one object whose
        // correctness the whole product rests on. Dropping the result costs
        // nothing — the live loop is about to probe anyway.
        if (isStale(booked)) {
            return;
        }

        // elapsedRealtime, not currentTimeMillis: the schedule must not jump
        // when the clock is corrected. PcState takes whatever monotonic scale
        // it is given.
        state.record(failure == null, SystemClock.elapsedRealtime());

        // Posted on the difference from what was last *delivered*, not on
        // record()'s boolean. In the steady state the two agree and nothing is
        // posted, so this stays as quiet as the transition-only contract
        // requires; after a dropped delivery they disagree and the marker
        // finally lands, one poll late instead of never.
        PcState.State observed = state.state();
        if (observed != delivered) {
            main.post(() -> deliver(observed, failure, booked));
        }

        if (!isStale(booked)) {
            try {
                owner.schedule(
                        () -> poll(owner, booked),
                        state.nextIntervalMs(),
                        TimeUnit.MILLISECONDS);
            } catch (RejectedExecutionException stopped) {
                // stop() landed between the check and the schedule. Nothing to
                // do: the loop is supposed to end.
            }
        }
    }

    /** Whether this probe belongs to a loop that has since been stopped or replaced. */
    private boolean isStale(int booked) {
        return !running || booked != generation;
    }

    /**
     * The main thread, for transitions only. Marking every poll would drown the
     * log and turn TT.6's "exactly one marker" count into noise, so this logs
     * on the difference between {@link #delivered} and what the probe observed,
     * and returns silently when they already agree.
     *
     * <p>T4.3 hangs the screen off this method. It runs on the main thread
     * because that is where the window can be touched, and {@link #isStale} —
     * not a bare {@code running} check — gates it, because a transition
     * detected microseconds before {@code onPause} must not drive a window the
     * Activity has already given up. Dropping it here is safe precisely because
     * {@code delivered} is left alone: the next generation's first poll sees
     * the disagreement and delivers it then.
     */
    private void deliver(PcState.State observed, String failure, int booked) {
        if (isStale(booked) || observed == delivered) {
            return;
        }
        delivered = observed;
        Log.i(TAG, observed == PcState.State.ONLINE ? "state=online" : "state=offline");
        if (failure != null) {
            // The reason, once per transition rather than once per poll, and on
            // its own line so it can never be mistaken for a state marker. A
            // panel stuck offline is the project's most confusing failure —
            // a moved PC, a closed port, a cleartext address the pin does not
            // cover all look identical from the outside — and this is the line
            // that tells them apart. It is also where Android's "Cleartext HTTP
            // traffic to ... not permitted" surfaces: the platform raises it as
            // an exception, and an exception nobody prints is a silent offline.
            Log.w(TAG, "probe failed: " + failure);
        }
    }

    /**
     * {@code GET /ping}, blocking, on the poller thread — never the main one,
     * where it would be a {@code NetworkOnMainThreadException}.
     *
     * @return null for a 200, and otherwise a short description of what went
     *         wrong. Every non-null value means exactly the same thing to
     *         {@link PcState} — timeout, connection refused, unreachable
     *         network, a 500, a truncated body are one answer, because the
     *         panel only ever needed one bit. The text is for the log.
     */
    private String probe() {
        HttpURLConnection connection = null;
        String failure = "not attempted";
        try {
            connection = (HttpURLConnection) new URL(pingUrl).openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(TIMEOUT_MS);
            connection.setReadTimeout(TIMEOUT_MS);
            connection.setUseCaches(false);
            int code = connection.getResponseCode();
            boolean ok = code == HttpURLConnection.HTTP_OK;
            drain(ok ? connection.getInputStream() : connection.getErrorStream());
            failure = ok ? null : "HTTP " + code;
        } catch (IOException | RuntimeException thrown) {
            // Swallowed rather than rethrown: an exception escaping here would
            // kill the scheduled task silently and the panel would freeze on
            // its last state. toString(), not getMessage(), so a class with no
            // message still says something.
            failure = thrown.toString();
        } finally {
            // Draining leaves a successful connection in the pool rather than
            // tearing it down, which is the cheap default if the peer ever
            // keeps it alive. Today it does not: server.py leaves
            // BaseHTTPRequestHandler on HTTP/1.0, so it closes after every
            // response and each poll is a fresh handshake regardless. The
            // asymmetry is kept anyway — it costs nothing, and it is the half
            // that would start paying the moment the server sets
            // protocol_version. A failed connection has nothing worth keeping.
            if (failure != null && connection != null) {
                connection.disconnect();
            }
        }
        return failure;
    }

    /** Reads the body to the end and closes it, so the socket can be reused. */
    private static void drain(InputStream body) throws IOException {
        if (body == null) {
            return;
        }
        try (InputStream in = body) {
            byte[] buffer = new byte[256];
            while (in.read(buffer) >= 0) {
                // The body says nothing the state machine needs; the status
                // line already answered the question.
            }
        }
    }
}
