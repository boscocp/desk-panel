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
