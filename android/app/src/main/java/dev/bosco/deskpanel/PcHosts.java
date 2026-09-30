package dev.bosco.deskpanel;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * The PCs this panel follows, and which of them answered last (ADR 0016).
 *
 * <p>The panel used to follow exactly one PC, pinned at build time. With more
 * than one — a Windows desktop and a Mac on the same desk — "online" becomes
 * <em>some</em> listed PC answering {@code /ping}, which is still invariant 2:
 * each server lives and dies with its own user's graphical session, so any one
 * answering means a human is logged in at one of those screens.
 *
 * <p>The host that answered last is asked first, and is the one data and
 * actions go to. That is what keeps the cost of a second PC near zero while one
 * is up — one probe per cycle, the same as before — and what stops the panel
 * flapping between two PCs that are both on: it moves only when the one it is
 * on stops answering.
 *
 * <p>Plain Java, no Android imports, so {@code ./gradlew test} covers it. The
 * active host is read by the data poller's thread and written by the PC
 * poller's, hence volatile; the list itself never changes after parsing.
 */
public final class PcHosts {

    /**
     * The most hosts a build may list. An offline cycle asks every one, at up
     * to 3 s each (connect plus read timeout), and the dormant probe runs
     * under {@code PanelService.PROBE_WINDOW_MS}, a 10 s wake lock: three
     * hosts is 9 s and fits, four would let the CPU suspend mid-cycle. The
     * build enforces the same number (found by review).
     */
    public static final int MAX_HOSTS = 3;

    /**
     * What a prober returns for a PC that answered and said its display is off
     * (ADR 0020). Compared by {@code equals}, and no failure text can collide
     * with it: failures are exception strings and {@code "HTTP <code>"}.
     */
    public static final String DISPLAY_OFF = "display off";

    /**
     * One {@code /ping} against one host: null for a 200 from a PC whose
     * display is on or unknown, {@link #DISPLAY_OFF} for a 200 from one whose
     * display is off, and anything else is why it failed.
     */
    public interface Prober {
        String probe(String host);
    }

    /**
     * Pure: whether a {@code /ping} body says the display is off. Only the
     * literal {@code "off"} counts. A server from before T4.6 sends no
     * {@code display} at all, one that cannot tell sends {@code "unknown"},
     * and a body that does not parse is not evidence of anything — all three
     * are "on", which is the panel as it behaved before (ADR 0020).
     */
    public static boolean displayOff(String body) {
        if (body == null) {
            return false;
        }
        try {
            return "off".equals(new JSONObject(body).optString("display"));
        } catch (JSONException malformed) {
            return false;
        }
    }

    /** Asked between hosts, so a stopped loop does not keep dialling. */
    public interface Stopped {
        boolean now();
    }

    /** What one cycle found. */
    public static final class Cycle {
        /** Null if some host answered, else every host's failure, for the log. */
        public final String failure;
        /** Whether the host that answered is a different one from last time. */
        public final boolean moved;
        /** The host that answered, or null. */
        public final String host;
        /**
         * Whether the host that answered said its display is off. True only
         * when no listed PC answered with its display on (ADR 0020).
         */
        public final boolean idle;

        Cycle(String failure, boolean moved, String host, boolean idle) {
            this.failure = failure;
            this.moved = moved;
            this.host = host;
            this.idle = idle;
        }
    }

    private final List<String> hosts;

    private volatile String active;

    private PcHosts(List<String> hosts) {
        this.hosts = Collections.unmodifiableList(hosts);
        this.active = hosts.get(0);
    }

    /**
     * From {@code R.string.pc_host}, which the build writes as a
     * comma-separated list from {@code PC_IP} in {@code .env}. Blanks are
     * dropped and a repeated host is kept once, in its first position.
     *
     * @throws IllegalArgumentException if nothing is left: a panel with no
     *         host would report offline for ever, which is indistinguishable
     *         from every PC being off, so it fails where it can be seen.
     */
    public static PcHosts parse(String csv) {
        LinkedHashSet<String> unique = new LinkedHashSet<>();
        if (csv != null) {
            for (String part : csv.split(",")) {
                String host = part.trim();
                if (!host.isEmpty()) {
                    unique.add(host);
                }
            }
        }
        if (unique.isEmpty()) {
            throw new IllegalArgumentException("no PC host configured: '" + csv + "'");
        }
        if (unique.size() > MAX_HOSTS) {
            throw new IllegalArgumentException(
                    "more than " + MAX_HOSTS + " PC hosts configured: '" + csv + "'");
        }
        return new PcHosts(new ArrayList<>(unique));
    }

    /** Every configured host, in the order {@code .env} lists them. */
    public List<String> all() {
        return hosts;
    }

    /** The host that answered last, or the first listed before any has. */
    public String active() {
        return active;
    }

    /** The order to probe in this cycle: the active host, then the rest as listed. */
    public List<String> probeOrder() {
        String current = active;
        List<String> order = new ArrayList<>(hosts.size());
        order.add(current);
        for (String host : hosts) {
            if (!host.equals(current)) {
                order.add(host);
            }
        }
        return order;
    }

    /**
     * One poll cycle: each host in {@link #probeOrder()}, stopping at the first
     * that answers with its display on and making it the active one. The loop
     * lives here rather than in {@code PcPoller} so the order and the move are
     * covered on the JVM; the poller only supplies the socket.
     *
     * <p>A PC that answers with its display off does not end the cycle: another
     * listed PC may have somebody at it, and that one should win (ADR 0020).
     * Only when none does is the cycle idle, on the first idle host found —
     * the active one, if it is idle, so two dark PCs do not flap either.
     */
    public Cycle cycle(Prober prober, Stopped stopped) {
        StringBuilder failures = new StringBuilder();
        String idleHost = null;
        for (String host : probeOrder()) {
            if (stopped.now()) {
                break;
            }
            String failure = prober.probe(host);
            if (failure == null) {
                return new Cycle(null, answered(host), host, false);
            }
            if (DISPLAY_OFF.equals(failure)) {
                if (idleHost == null) {
                    idleHost = host;
                }
                continue;
            }
            if (failures.length() > 0) {
                failures.append("; ");
            }
            failures.append(host).append(": ").append(failure);
        }
        if (idleHost != null) {
            return new Cycle(null, answered(idleHost), idleHost, true);
        }
        return new Cycle(failures.length() > 0 ? failures.toString() : "not attempted",
                false, null, false);
    }

    /**
     * Records that {@code host} answered.
     *
     * @return whether that moved the panel to a different PC
     * @throws IllegalArgumentException for a host that is not in the list,
     *         which would mean the poller dialled something the cleartext pin
     *         does not cover
     */
    public boolean answered(String host) {
        if (!hosts.contains(host)) {
            throw new IllegalArgumentException("not a configured PC host: " + host);
        }
        boolean moved = !host.equals(active);
        active = host;
        return moved;
    }
}
