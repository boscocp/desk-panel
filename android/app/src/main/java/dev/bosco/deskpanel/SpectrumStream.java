package dev.bosco.deskpanel;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Reads {@code GET /spectrum} from the PC and hands each frame to the panel
 * (T8.5, ADR 0021).
 *
 * <p>The third network loop, beside {@link PcPoller} and {@link DataPoller},
 * and deliberately not folded into either: those ask and wait on a clock of
 * seconds, this holds one connection open and reads twenty lines a second.
 * Like them it is the app's network code and the page has none (invariant 1).
 *
 * <p><b>It runs only while the PC is online</b>, started and stopped by
 * {@code PanelService} beside the data poller, so a dark panel holds no
 * socket and the PC captures nothing.
 *
 * <p>Frames are coalesced on the way to the main thread: at most one is ever
 * queued, and a newer one replaces it. A main thread that falls behind skips
 * frames instead of drawing a backlog late.
 */
public final class SpectrumStream {

    /** Receives one frame, on the main thread. */
    public interface Listener {
        /** @param frame 32 lowercase hex digits, checked by {@link SpectrumFrame} */
        void onSpectrum(String frame);
    }

    private static final int CONNECT_TIMEOUT_MS = 5000;

    /**
     * Longer than the server's five-second keepalive, so a live stream never
     * trips it and a dead one is found within this.
     */
    private static final int READ_TIMEOUT_MS = 15_000;

    /** After a stream the server ended on purpose: reopen at once, nearly. */
    private static final long REOPEN_MS = 500L;

    /** After a failure: the PC is up (the ping says so) but the stream is not. */
    private static final long RETRY_MS = 5_000L;

    /**
     * After a 404: the bars are off in the PC's config, or it cannot capture.
     * Asked again now and then, so turning them on is a restart of the
     * server and not of the panel.
     */
    private static final long OFF_RETRY_MS = 60_000L;

    private final PcHosts hosts;
    private final PanelLink link;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final AtomicReference<String> pending = new AtomicReference<>();

    private volatile boolean running;
    private volatile int generation;
    private volatile HttpURLConnection current;

    public SpectrumStream(PcHosts hosts, PanelLink link, Listener listener) {
        this.hosts = hosts;
        this.link = link;
        this.listener = listener;
    }

    /** Opens the stream on a thread of its own. Calling it twice is a no-op. */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        final int booked = ++generation;
        Thread thread = new Thread(() -> loop(booked), "spectrum");
        thread.setDaemon(true);
        thread.start();
    }

    /**
     * Stops reading. The connection is closed from here, because a thread
     * blocked in a socket read does not answer an interrupt.
     */
    public void stop() {
        if (!running) {
            return;
        }
        running = false;
        generation++;
        HttpURLConnection connection = current;
        if (connection != null) {
            connection.disconnect();
        }
    }

    private boolean isStale(int booked) {
        return !running || booked != generation;
    }

    private void loop(int booked) {
        while (!isStale(booked)) {
            long delay;
            try {
                delay = readOnce(booked);
            } catch (Throwable unexpected) {
                Log.e(Markers.TAG, "spectrum stream failed", unexpected);
                delay = RETRY_MS;
            }
            if (isStale(booked)) {
                return;
            }
            try {
                Thread.sleep(delay);
            } catch (InterruptedException interrupted) {
                return;
            }
        }
    }

    /** One connection, read to its end. Returns how long to wait before the next. */
    private long readOnce(int booked) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(
                    link.base(hosts.active()) + "/spectrum").openConnection();
            String key = link.key();
            if (key != null) {
                connection.setRequestProperty(PanelLink.KEY_HEADER, key);
            }
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setUseCaches(false);
            current = connection;
            if (isStale(booked)) {
                return 0;
            }
            int status = connection.getResponseCode();
            if (status == HttpURLConnection.HTTP_NOT_FOUND) {
                Log.i(Markers.TAG, Markers.spectrum("off"));
                return OFF_RETRY_MS;
            }
            if (status != HttpURLConnection.HTTP_OK) {
                Log.w(Markers.TAG, Markers.spectrum("err") + " status=" + status);
                return RETRY_MS;
            }
            Log.i(Markers.TAG, Markers.spectrum("open"));
            BufferedReader reader = new BufferedReader(new InputStreamReader(
                    connection.getInputStream(), StandardCharsets.US_ASCII));
            String line;
            while ((line = reader.readLine()) != null && !isStale(booked)) {
                String frame = SpectrumFrame.parse(line);
                if (frame != null) {
                    deliver(frame, booked);
                }
            }
            if (!isStale(booked)) {
                Log.i(Markers.TAG, Markers.spectrum("end"));
            }
            return REOPEN_MS;
        } catch (IOException | RuntimeException failed) {
            if (!isStale(booked)) {
                Log.w(Markers.TAG, Markers.spectrum("err") + " " + failed.getClass().getSimpleName());
            }
            return RETRY_MS;
        } finally {
            current = null;
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void deliver(String frame, int booked) {
        if (pending.getAndSet(frame) != null) {
            return;
        }
        main.post(() -> {
            String latest = pending.getAndSet(null);
            if (latest != null && !isStale(booked)) {
                listener.onSpectrum(latest);
            }
        });
    }
}
