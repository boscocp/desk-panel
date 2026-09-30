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

    /**
     * Told about transitions, on the main thread, and only about transitions.
     * {@code PanelService} implements it: this class owns the socket and the
     * schedule, and nothing that happens as a consequence of the answer — the
     * marker, the wake lock, the screen — which is why it does not log the
     * state itself.
     */
    public interface Listener {
        /**
         * @param state ONLINE when a PC answered with its display on, IDLE when
         *              one answered with it off, OFFLINE when none answered.
         *              Only ONLINE lights the panel.
         */
        void onPcState(PcState.State state);

        /**
         * Called on the main thread when this poller has deliberately booked
         * nothing, because the state is dormant — offline and on battery
         * (T5.6). It is the handover: from here until something calls
         * {@link #probeNow()}, no probe will happen, and the schedule is the
         * listener's problem.
         *
         * <p>Fired after every dormant cycle rather than once on entering
         * dormancy, and that is deliberate: it is the only thing that re-arms
         * the alarm after a probe that found the PC still absent, so a
         * once-only edge would leave the phone asleep for good.
         */
        void onDormant();
    }

    /**
     * The PC server's plain port (T3.1). {@code /ping} stays here even when
     * data moves to TLS, because it is the login signal (ADR 0018).
     */
    private static final int PORT = PanelLink.PLAIN_PORT;

    /**
     * Connect and read timeout, applied to both ends of the probe.
     *
     * <p>Deliberately shorter than {@link PcState#ONLINE_INTERVAL_MS}: the
     * failure path has to be as prompt as the success path, because switching
     * the screen off when the PC disappears is the whole product. The platform
     * default is measured in tens of seconds, which would let a dead PC look
     * alive for most of a minute. At 1500 ms a probe against a host that has
     * gone away reaches the offline marker within about a second and a half of
     * the poll that was due. There is no DNS to bound — the host is a bare
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

    /** Far above {@code {"ok": true, "display": "unknown"}}, far below harm. */
    private static final int MAX_PING_BYTES = 1024;

    /**
     * The PCs to ask, and which one answered last (ADR 0016). One cycle asks
     * the active host first and stops at the first 200, so while a PC is up a
     * cycle costs one probe however many are listed. Offline, a cycle asks
     * every host in turn, and its worst case is that many times 3000 ms --
     * {@link #TIMEOUT_MS} twice, connect and read -- which is why
     * {@link PcHosts#MAX_HOSTS} exists and why the {@link #generation} guard
     * matters more here than it did with one host.
     */
    private final PcHosts hosts;

    private final Listener listener;

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

    /**
     * Whether the charger is connected, as last reported by the service from
     * {@code EXTRA_PLUGGED} (T5.4).
     *
     * <p>Starts true, which is the safe default and not an optimistic one: if
     * no battery broadcast ever arrives, this poller behaves exactly as it did
     * before T5.6 — the ladder and the wake lock — rather than going dormant on
     * a phone that is plainly charging and never probing again.
     */
    private volatile boolean onMains = true;

    private volatile ScheduledExecutorService scheduler;

    /**
     * @param hosts the PCs' LAN addresses, from {@code R.string.pc_host}, which
     *              the build substitutes from {@code .env} (ADR 0013). They are
     *              the hosts {@code network_security_config.xml} allows in
     *              cleartext, one {@code <domain>} each inside a single
     *              {@code domain-config} (ADR 0016).
     * @param listener told about transitions, on the main thread
     */
    public PcPoller(PcHosts hosts, Listener listener) {
        this.hosts = hosts;
        this.listener = listener;
    }

    /**
     * Begins polling, first probe immediately. Called from {@code
     * PanelService.onStartCommand}; calling it twice is a no-op, so a second
     * start command cannot leave two loops running.
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
     * Tells this poller whether the charger is connected (T5.6). Cheap and
     * idempotent: it only decides what {@link #reschedule} does at the end of
     * the next cycle, so the caller can hand it every battery broadcast without
     * thinking about edges.
     *
     * <p>It deliberately does <em>not</em> probe or reschedule. Power returning
     * is worth an immediate probe, but that is an edge only the caller can see,
     * and it asks for it with {@link #probeNow()}.
     */
    public void setOnMains(boolean connected) {
        onMains = connected;
    }

    /**
     * Probes once, now, on the poller thread — the way out of dormancy.
     *
     * <p>No new schedule and no new generation: it books one cycle onto the
     * loop that is already there but idle, so the cycle ends in the usual
     * {@link #reschedule}, which decides what happens next from the state it
     * finds. That is what makes recovery need no special case — a probe that
     * finds the PC back lands on the 2s ladder, and one that finds it still
     * gone hands the schedule straight back to the alarm.
     *
     * <p>A no-op if the poller is stopped.
     *
     * <p><b>It takes a new generation</b>, which is what stops it forking the
     * chain. Every cycle ends in a reschedule, so submitting one alongside a
     * cycle that is already booked would leave two chains rescheduling each
     * other for the life of the process — the panel polling at double rate
     * overnight, which is the failure {@link #generation} was introduced to
     * prevent and the one case it could not catch, because the extra chain
     * carried the current number. Bumping it abandons whatever was pending and
     * makes this the only live chain. Two triggers arriving together — the
     * alarm coming due as the charger goes in — therefore cost one chain, not
     * two.
     */
    public void probeNow() {
        ScheduledExecutorService owner = scheduler;
        if (!running || owner == null) {
            return;
        }
        final int booked = ++generation;
        try {
            owner.execute(() -> poll(owner, booked));
        } catch (RejectedExecutionException stopped) {
            // stop() landed between the read and the submit. Nothing to do.
        }
    }

    /**
     * Stops polling and releases the thread. Called from {@code
     * PanelService.onDestroy} — a poller that outlives its owner is a leak that
     * shows up as an overnight battery complaint rather than as a crash.
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
        try {
            probeAndDeliver(booked);
        } catch (Throwable unexpected) {
            // The reschedule below is in a finally, so this catch is not what
            // keeps the loop alive — it is what keeps the reason visible. An
            // exception reaching a ScheduledExecutorService's runnable is
            // swallowed whole: the Future holds it and nobody ever calls get(),
            // so without this line the only trace of a broken poll would be the
            // panel quietly not changing (T5.2 step 2).
            //
            // Throwable, not Exception: an Error on this thread — an OOM while
            // reading a body, a NoClassDefFoundError from a component that was
            // never going to load — ends the chain exactly as thoroughly as a
            // RuntimeException does, and the panel cannot do anything useful by
            // dying with it.
            Log.e(Markers.TAG, "poll cycle failed", unexpected);
        } finally {
            reschedule(owner, booked);
        }
    }

    /**
     * One probe and whatever it means, with no scheduling of its own. Split out
     * so the reschedule can sit in a {@code finally} and be unreachable by an
     * exception: a loop that stops rescheduling is the failure this task calls
     * the worst available, because the panel keeps showing its last state and
     * nothing anywhere says the loop is gone.
     */
    private void probeAndDeliver(int booked) {
        if (isStale(booked)) {
            return;
        }

        PcHosts.Cycle cycle = probeAll(booked);
        String failure = cycle.failure;

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
        state.record(failure == null, cycle.idle, SystemClock.elapsedRealtime());

        // One line per probe, which is what makes the backoff assertable (T5.3):
        // "at most four polls a minute while the PC is off" cannot be read off a
        // log that only speaks on transitions, and the offline stretch is by
        // definition the one with no transitions in it. Logged here rather than
        // in deliver(), which fires on edges only, and after the staleness check
        // above so a straggler from a replaced generation cannot inflate the
        // count with polls that are no longer anybody's cadence.
        Log.i(Markers.TAG, Markers.ping(failure != null ? "err" : cycle.idle ? "idle" : "ok"));

        // Posted on the difference from what was last *delivered*, not on
        // record()'s boolean. In the steady state the two agree and nothing is
        // posted, so this stays as quiet as the transition-only contract
        // requires; after a dropped delivery they disagree and the marker
        // finally lands, one poll late instead of never.
        PcState.State observed = state.state();
        if (observed != delivered) {
            main.post(() -> deliver(observed, failure, booked));
        }
    }

    /**
     * Books the next probe at whatever interval {@link PcState} asks for, or
     * books nothing if this generation has been stopped or replaced.
     *
     * <p>Called from a {@code finally}, so it runs whether the cycle succeeded,
     * threw, or returned early. That is the whole point: the chain is only as
     * durable as its least-guarded link, and every link that is not this one
     * ends the loop for the life of the process when it breaks.
     */
    private void reschedule(ScheduledExecutorService owner, int booked) {
        if (isStale(booked)) {
            return;
        }
        if (state.isDormant(onMains)) {
            // Books nothing, on purpose. Offline and on battery, this process
            // must not be the reason the CPU stays up, and a scheduled task is
            // exactly that reason -- either it holds a wake lock so it can fire
            // or the device suspends and it does not fire at all. So the
            // schedule goes to AlarmManager and this loop goes quiet until
            // probeNow().
            main.post(this::notifyDormant);
            return;
        }
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

    /**
     * The dormancy handover, on the main thread for the same reason the state
     * is delivered there: what the listener does with it touches the wake lock
     * and the alarm, which are window-and-service concerns rather than socket
     * ones.
     *
     * <p>Re-checked against {@code running} rather than a generation, because
     * by the time this runs the loop may have been stopped — and arming an
     * alarm on behalf of a poller that no longer exists would wake the phone
     * every fifteen minutes for nothing.
     */
    private void notifyDormant() {
        if (running) {
            listener.onDormant();
        }
    }

    /** Whether this probe belongs to a loop that has since been stopped or replaced. */
    private boolean isStale(int booked) {
        return !running || booked != generation;
    }

    /**
     * The main thread, for transitions only. Reporting every poll would drown
     * the log and turn TT.6's "exactly one marker" count into noise, so this
     * fires on the difference between {@link #delivered} and what the probe
     * observed, and returns silently when they already agree.
     *
     * <p>The screen hangs off this method, through the listener (T4.3). It runs
     * on the main thread because that is where the window can be touched, and
     * {@link #isStale} — not a bare {@code running} check — gates it, because a
     * transition detected microseconds before a stop must not drive a window
     * its Activity has already given up. Dropping it here is safe precisely
     * because {@code delivered} is left alone: the next generation's first poll
     * sees the disagreement and delivers it then.
     */
    private void deliver(PcState.State observed, String failure, int booked) {
        if (isStale(booked) || observed == delivered) {
            return;
        }
        delivered = observed;
        listener.onPcState(observed);
        if (failure != null) {
            // The reason, once per transition rather than once per poll, and on
            // its own line so it can never be mistaken for a state marker. A
            // panel stuck offline is the project's most confusing failure —
            // a moved PC, a closed port, a cleartext address the pin does not
            // cover all look identical from the outside — and this is the line
            // that tells them apart. It is also where Android's "Cleartext HTTP
            // traffic to ... not permitted" surfaces: the platform raises it as
            // an exception, and an exception nobody prints is a silent offline.
            Log.w(Markers.TAG, "probe failed: " + failure);
        }
    }

    /**
     * One {@code /ping} per host, in {@link PcHosts#probeOrder()}, stopping at
     * the first that answers. Staleness is re-checked between hosts, so a
     * stopped loop does not spend the rest of a long offline cycle dialling.
     *
     * @return the cycle: its failure is null if some host answered, and
     *         otherwise every host's failure, for the log line {@link #deliver}
     *         writes once per transition
     */
    private PcHosts.Cycle probeAll(int booked) {
        PcHosts.Cycle cycle = hosts.cycle(
                host -> probe("http://" + host + ":" + PORT + "/ping"),
                () -> isStale(booked));
        if (cycle.moved) {
            // Not a marker: the state did not change, only which PC is
            // serving it. Plain text, like "probe failed:", so it can never be
            // mistaken for one.
            Log.i(Markers.TAG, "pc answered at " + cycle.host);
        }
        return cycle;
    }

    /**
     * {@code GET /ping}, blocking, on the poller thread — never the main one,
     * where it would be a {@code NetworkOnMainThreadException}.
     *
     * @return null for a 200, {@link PcHosts#DISPLAY_OFF} for a 200 whose
     *         body says the display is off (ADR 0020), and otherwise a short
     *         description of what went wrong. Every other value means exactly
     *         the same thing to {@link PcState} — timeout, connection refused,
     *         unreachable network, a 500, a truncated body are one answer. The
     *         text is for the log.
     */
    private String probe(String pingUrl) {
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
            if (ok) {
                failure = PcHosts.displayOff(read(connection.getInputStream()))
                        ? PcHosts.DISPLAY_OFF : null;
            } else {
                drain(connection.getErrorStream());
                failure = "HTTP " + code;
            }
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
            if (failure != null && !PcHosts.DISPLAY_OFF.equals(failure) && connection != null) {
                connection.disconnect();
            }
        }
        return failure;
    }

    /**
     * Reads a {@code /ping} body, which is a few dozen bytes, and closes it.
     * Capped, so a peer that is not the desk-panel server cannot make the
     * poller hold an unbounded string: past the cap it returns null, which
     * {@link PcHosts#displayOff} reads as "on" -- the safe side.
     */
    private static String read(InputStream body) throws IOException {
        if (body == null) {
            return null;
        }
        try (InputStream in = body) {
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[256];
            int n;
            while ((n = in.read(buffer)) >= 0) {
                if (out.size() + n > MAX_PING_BYTES) {
                    return null;
                }
                out.write(buffer, 0, n);
            }
            return out.toString("UTF-8");
        }
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
