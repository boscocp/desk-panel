package dev.bosco.deskpanel;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;

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

    /** One {@code /ping} against one host: null for a 200, else why not. */
    public interface Prober {
        String probe(String host);
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

        Cycle(String failure, boolean moved, String host) {
            this.failure = failure;
            this.moved = moved;
            this.host = host;
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
     * that answers and making it the active one. The loop lives here rather
     * than in {@code PcPoller} so the order and the move are covered on the
     * JVM; the poller only supplies the socket.
     */
    public Cycle cycle(Prober prober, Stopped stopped) {
        StringBuilder failures = new StringBuilder();
        for (String host : probeOrder()) {
            if (stopped.now()) {
                break;
            }
            String failure = prober.probe(host);
            if (failure == null) {
                return new Cycle(null, answered(host), host);
            }
            if (failures.length() > 0) {
                failures.append("; ");
            }
            failures.append(host).append(": ").append(failure);
        }
        return new Cycle(failures.length() > 0 ? failures.toString() : "not attempted", false, null);
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
