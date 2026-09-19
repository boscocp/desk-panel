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

    /** The PC server's port. Shared with {@link PcPoller} by construction. */
    private static final int PORT = 8777;

    /**
     * Longer than {@link PcPoller}'s, because a failed data fetch is not
     * urgent: the panel keeps the last values and the server has its own
     * cache and its own stale flag underneath.
     */
    private static final int TIMEOUT_MS = 5000;

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

    /** Retried sooner than a success, but not so soon that a dead server is hammered. */
    private static final long RETRY_MS = 15_000L;

    /** A response larger than this is not the payload; it is something wrong. */
    private static final int MAX_BODY_BYTES = 256 * 1024;

    /** Receives the merged payload, on the main thread. */
    public interface Listener {
        /** @param json a JSON object literal, ready to hand to the page */
        void onData(String json);
    }

    private final String quotesUrl;
    private final String weatherUrl;
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

    public DataPoller(String host, Listener listener) {
        this.quotesUrl = "http://" + host + ":" + PORT + "/quotes";
        this.weatherUrl = "http://" + host + ":" + PORT + "/weather";
        this.listener = listener;
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

    private void poll(ScheduledExecutorService owner, int booked) {
        if (isStale(booked)) {
            return;
        }

        String quotes = get(quotesUrl);
        String weather = get(weatherUrl);

        if (isStale(booked)) {
            return;
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

        if (!isStale(booked)) {
            try {
                owner.schedule(() -> poll(owner, booked),
                        ok ? INTERVAL_MS : RETRY_MS, TimeUnit.MILLISECONDS);
            } catch (RejectedExecutionException stopped) {
                // stop() landed between the check and the schedule.
            }
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
