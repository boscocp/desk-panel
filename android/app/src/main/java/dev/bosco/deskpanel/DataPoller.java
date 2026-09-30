package dev.bosco.deskpanel;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Fetches {@code /quotes} and {@code /weather} from the PC and hands the panel
 * one merged payload (T5.1).
 *
 * <p>Sibling to {@link PcPoller}, and deliberately not merged with it. They
 * answer different questions on different clocks: the ping is a 2s heartbeat
 * that decides whether the screen is on at all, while this is a slow refresh of
 * what the screen shows. The server caches for {@code quotes_interval_s} and
 * {@code weather_interval_s}, so asking faster than this returns the same bytes
 * and spends the phone's radio for nothing.
 *
 * <p><b>It only runs while the PC is online.</b> {@code PanelService} starts it
 * on the transition up and stops it on the way down (T5.1 step 4), which is not
 * only politeness: offline, the panel is dark and the device is asleep on a
 * wake lock held to notice a login, and a data poll there would spend that
 * budget rendering pixels nobody can see (ADR 0008).
 *
 * <p>Like {@code PcPoller}, this is the app's network code and the page has
 * none — {@code web/} never calls {@code fetch} (invariant 1, ADR 0002). What
 * arrives here is pushed into the page through {@code window.onData}, the same
 * entry point {@code web/js/mock.js} drives in a browser, so the panel is built
 * and reviewed without any of this running.
 */
public final class DataPoller {

    /**
     * Longer than {@link PcPoller}'s, because a failed data fetch is not
     * urgent: the panel keeps the last values and the server has its own
     * cache and its own stale flag underneath.
     */
    private static final int TIMEOUT_MS = 5000;

    /**
     * How long a shortcut press may wait for the PC, and it is deliberately
     * not {@link #TIMEOUT_MS} (T8.2).
     *
     * <p>The number is dictated by the other end: {@code actions.timeout_for}
     * allows a press <b>15 seconds</b> on Windows, because the mixer call
     * there is PowerShell handing C# to {@code Add-Type} and the compiler runs
     * on every press. Five seconds here would give up first, log
     * {@code result=err} and make the button say it failed — on a PC that then
     * mutes a few seconds later. A button that lies about a mute is the one
     * thing T8.2 step 7 forbids, and "it did nothing" is indistinguishable
     * from "it worked" by ear.
     *
     * <p>Only the read timeout: connecting is a LAN handshake and still gets
     * {@link #TIMEOUT_MS}, so an absent PC is still refused in five seconds
     * rather than twenty.
     */
    private static final int ACTION_TIMEOUT_MS = 20000;

    /**
     * How often to ask. Well apart from the 2s ping on purpose, and shorter
     * than the server's own cache windows so a cache that has just expired is
     * picked up promptly rather than a whole interval late.
     *
     * <p>Not read from config, and that is a deliberate asymmetry: the server
     * decides how often to hit an upstream, the phone only decides how often
     * to ask a server that is already caching. A value here cannot burn
     * anybody's API budget.
     */
    private static final long INTERVAL_MS = 60_000L;

    /** What the page is told when the PC did not say. Matches server/actions.py. */
    private static final String STATE_UNKNOWN = "unknown";

    /** Retried sooner than a success, but not so soon that a dead server is hammered. */
    private static final long RETRY_MS = 15_000L;

    /** A response larger than this is not the payload; it is something wrong. */
    private static final int MAX_BODY_BYTES = 256 * 1024;

    /** Receives the merged payload, on the main thread. */
    public interface Listener {
        /** @param json a JSON object literal, ready to hand to the page */
        void onData(String json);
    }

    /**
     * Receives the outcome of one shortcut press, on the main thread.
     *
     * <p>Separate from {@link Listener} because the two have different
     * lifetimes: the data listener is the panel for as long as the poller
     * lives, and this is one press.
     */
    public interface ResultListener {
        /**
         * @param id    an id from {@link Actions#ALLOWED}, never the page's string
         * @param ok    whether the PC answered 200
         * @param state what the PC said the mixer now holds -- {@code muted},
         *              {@code unmuted}, or {@code unknown}. Never null, and
         *              {@code unknown} on any failure: a state the panel drew
         *              on a guess is the one thing ADR 0015 forbids
         */
        void onActionResult(String id, boolean ok, String state);
    }

    /**
     * Read per request, never cached as a URL: the PC this panel is on can
     * change while it stays online -- one of two PCs going away while the
     * other answers -- and data and presses must follow it (ADR 0016).
     */
    private final PcHosts hosts;
    private final Listener listener;

    private final Handler main = new Handler(Looper.getMainLooper());

    private volatile boolean running;

    /**
     * The same straggler guard {@link PcPoller} carries, and for the same
     * reason: blocking socket I/O on Android does not answer an interrupt, so
     * a probe already inside {@code getResponseCode()} runs to its timeout and
     * comes back into a process that may have started a second loop. Without
     * this counter the panel would poll at twice the rate for the rest of the
     * session, one extra chain per online transition.
     */
    private volatile int generation;

    private volatile ScheduledExecutorService scheduler;

    /** Scheme, port and key for data and presses (T9.4, ADR 0018). */
    private final PanelLink link;

    public DataPoller(PcHosts hosts, PanelLink link, Listener listener) {
        this.hosts = hosts;
        this.link = link;
        this.listener = listener;
    }

    private String url(String host, String path) {
        return link.base(host) + path;
    }

    /**
     * The key, on every data request and every press, when the traffic is
     * private. Set on the connection rather than in the URL, so it never
     * reaches a log line that prints one.
     */
    private void authenticate(HttpURLConnection connection) {
        String key = link.key();
        if (key != null) {
            connection.setRequestProperty(PanelLink.KEY_HEADER, key);
        }
    }

    /** Begins polling, first fetch immediately. Calling it twice is a no-op. */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        final int booked = ++generation;
        final ScheduledExecutorService owner = Executors.newSingleThreadScheduledExecutor(
                runnable -> {
                    Thread thread = new Thread(runnable, "data-poller");
                    thread.setDaemon(true);
                    return thread;
                });
        scheduler = owner;
        owner.execute(() -> poll(owner, booked));
    }

    /** Stops polling and releases the thread. */
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
     * Fires one shortcut action at the PC (T8.2). Returns whether it was sent.
     *
     * <p><b>Why this lives in the data poller.</b> T8.2 asks for the request to
     * go onto the executor this class already owns rather than a new one, and
     * the reason turns out to be stronger than thread economy: that executor
     * exists exactly while the PC is online, because {@code PanelService}
     * starts this poller on the transition up and stops it on the way down.
     * So "the buttons are dead while the PC is away" (T8.2 step 3) is a
     * property of where the code lives rather than a check somebody has to
     * remember — there is no thread to run on, and {@link #running} is already
     * false.
     *
     * <p>That matters more than it sounds. A queued action would fire on
     * reconnect and mute the PC minutes after somebody pressed a button they
     * could not see, on a panel that was black at the time. Nothing here
     * queues: a press while offline is refused, logged and forgotten.
     *
     * @param candidate an id straight off the JavaScript bridge, untrusted and
     *                  resolved through {@link Actions} before it reaches a URL
     * @return false if it was refused outright — an unknown id, or the PC being
     *         away. True only means it was dispatched; the outcome arrives
     *         later through {@code onResult}.
     */
    public boolean invoke(String candidate, ResultListener onResult) {
        final String id = Actions.resolve(candidate);
        if (id == null) {
            // The page asked for something this app does not relay. Logged
            // with the raw string, because the only way this happens is a bug
            // in a theme or an asset that is not ours, and both are worth
            // seeing.
            Log.w(Markers.TAG, Markers.action(String.valueOf(candidate), "rejected"));
            return false;
        }
        final String url = Actions.urlFor(link, hosts.active(), id);
        final ScheduledExecutorService owner = scheduler;
        if (!running || owner == null || url == null) {
            Log.i(Markers.TAG, Markers.action(id, "offline"));
            return false;
        }
        try {
            owner.execute(() -> {
                String state = post(url);
                boolean ok = state != null;
                Log.i(Markers.TAG, Markers.action(id, ok ? "ok" : "err"));
                final String reported = ok ? state : STATE_UNKNOWN;
                if (onResult != null) {
                    main.post(() -> onResult.onActionResult(id, ok, reported));
                }
            });
        } catch (RejectedExecutionException stopped) {
            // The PC went away between the check above and here.
            Log.i(Markers.TAG, Markers.action(id, "offline"));
            return false;
        }
        return true;
    }

    /**
     * {@code POST url}, blocking, on the poller thread. No body and no headers.
     *
     * <p>Deliberately sends neither {@code Origin} nor {@code Sec-Fetch-Site}:
     * the server refuses a request carrying either, because those are what a
     * browser puts on a cross-origin form post and that is the drive-by ADR
     * 0015 was amended to close. {@code HttpURLConnection} sets neither on its
     * own, which is what makes the check free here — but it is worth knowing
     * before somebody adds a header for an unrelated reason.
     *
     * @return the {@code state} field of the 200's body -- {@code muted},
     *         {@code unmuted} or {@code unknown} -- or **null** for anything
     *         that was not a 200. Null is the failed press; every other
     *         outcome is a press that worked and a state the panel may draw.
     *         A 200 whose body cannot be read is {@code unknown} and not a
     *         failure: the PC did the thing, it just did not manage to say
     *         what the result was.
     */
    private String post(String url) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setRequestMethod("POST");
            authenticate(connection);
            connection.setConnectTimeout(TIMEOUT_MS);
            // Not TIMEOUT_MS: the PC is allowed 15s for this on Windows. See
            // ACTION_TIMEOUT_MS.
            connection.setReadTimeout(ACTION_TIMEOUT_MS);
            connection.setUseCaches(false);
            // No body at all: the id is in the path and there is nothing else
            // to say (ADR 0015). setFixedLengthStreamingMode(0) rather than
            // letting the connection buffer, so this cannot grow one by
            // accident later.
            connection.setDoOutput(false);
            connection.setFixedLengthStreamingMode(0);
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) {
                return null;
            }
            return DataPayload.actionState(read(connection.getInputStream()));
        } catch (IOException | RuntimeException thrown) {
            // Swallowed like get()'s: an exception escaping here would kill
            // the executor's task and the panel would keep polling with one
            // button that silently never works again.
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void poll(ScheduledExecutorService owner, int booked) {
        // A failed cycle is the safe assumption for the schedule: if the body
        // below dies before it has an answer, retrying sooner is the behaviour
        // that recovers, and RETRY_MS is still slow enough not to hammer a
        // server that may be the thing that is broken.
        long delayMs = RETRY_MS;
        try {
            delayMs = fetchAndDeliver(booked) ? INTERVAL_MS : RETRY_MS;
        } catch (Throwable unexpected) {
            // See PcPoller.poll: the reschedule is in the finally, so this is
            // about making the reason visible rather than about survival. A
            // scheduled runnable's exception goes into a Future nobody reads,
            // and the panel would simply stop refreshing with a healthy ping
            // and a full log of nothing (T5.2 step 2).
            Log.e(Markers.TAG, "data cycle failed", unexpected);
        } finally {
            reschedule(owner, booked, delayMs);
        }
    }

    /**
     * One fetch of both endpoints and, if they agree on a payload, one delivery.
     * Split from {@link #poll} so the reschedule can live in a {@code finally}
     * where no exception can step over it.
     *
     * @return whether the cycle produced a payload, which is the only thing the
     *         schedule needs to know
     */
    private boolean fetchAndDeliver(int booked) {
        if (isStale(booked)) {
            return true;
        }

        // One host for both halves, read once: a payload merged from two
        // PCs would pair one desk's tickers with the other's city.
        String host = hosts.active();
        String quotes = get(url(host, "/quotes"));
        String weather = get(url(host, "/weather"));

        if (isStale(booked)) {
            return true;
        }

        String payload = DataPayload.merge(quotes, weather);
        boolean ok = payload != null;

        // One line per cycle, at a bounded rate — this is the heartbeat TT.6
        // defines, and it is what makes "the panel has real data" assertable
        // instead of something a human confirms by looking.
        Log.i(Markers.TAG, Markers.data(ok));
        if (!ok) {
            // The reason, once per cycle. A panel stuck on old numbers with a
            // healthy ping looks identical to a panel nobody has updated.
            Log.w(Markers.TAG, "data fetch failed: quotes="
                    + (quotes == null ? "error" : "ok")
                    + " weather=" + (weather == null ? "error" : "ok"));
        } else {
            main.post(() -> deliver(payload, booked));
        }
        return ok;
    }

    /**
     * Books the next cycle, or books nothing if this generation has been
     * stopped or replaced. Called from a {@code finally} so that no failure
     * above it can leave the panel on numbers that never change again.
     */
    private void reschedule(ScheduledExecutorService owner, int booked, long delayMs) {
        if (isStale(booked)) {
            return;
        }
        try {
            owner.schedule(() -> poll(owner, booked), delayMs, TimeUnit.MILLISECONDS);
        } catch (RejectedExecutionException stopped) {
            // stop() landed between the check and the schedule.
        }
    }

    private void deliver(String payload, int booked) {
        if (isStale(booked)) {
            return;
        }
        listener.onData(payload);
    }

    private boolean isStale(int booked) {
        return !running || booked != generation;
    }

    /**
     * {@code GET url}, blocking, on the poller thread.
     *
     * @return the body as a string, or null for anything that was not a 200
     *         with a body. Every failure means the same thing to the caller:
     *         keep what the panel already has.
     */
    private String get(String url) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setRequestMethod("GET");
            authenticate(connection);
            connection.setConnectTimeout(TIMEOUT_MS);
            connection.setReadTimeout(TIMEOUT_MS);
            connection.setUseCaches(false);
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) {
                return null;
            }
            return read(connection.getInputStream());
        } catch (IOException | RuntimeException thrown) {
            // Swallowed rather than rethrown: an exception escaping here would
            // kill the scheduled task silently and the panel would freeze on
            // its last payload with no marker to say why.
            return null;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    /** Reads a bounded body as UTF-8. */
    private static String read(InputStream body) throws IOException {
        if (body == null) {
            return null;
        }
        try (InputStream in = body) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int read;
            while ((read = in.read(buffer)) >= 0) {
                if (out.size() + read > MAX_BODY_BYTES) {
                    // Bounded on purpose. The payload is a few hundred bytes;
                    // anything approaching this is a captive portal or a
                    // misrouted request, and reading it whole into a phone's
                    // heap is how a display becomes an OutOfMemoryError.
                    return null;
                }
                out.write(buffer, 0, read);
            }
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }
}
