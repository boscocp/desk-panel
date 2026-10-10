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

    /**
     * The longest short reason {@link #shortReason} will return. Long enough
     * for {@code SSLHandshakeException}, short enough that a line carrying one
     * per host stays a line.
     */
    private static final int MAX_REASON = 32;

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
        /**
         * Which PC this cycle was about, for the heartbeat line: {@code
         * host=<ip>} when one answered, {@code hosts=<ip>:<reason>,...} when
         * none did (T4.8).
         *
         * <p>It rides the per-cycle {@code ping=} line rather than the
         * per-transition one, because the question it answers — <em>which</em>
         * of the listed PCs is the panel on, and what did the others say — is
         * asked hours after the transition that would have answered it, and by
         * then the transition line is gone: the device's {@code main} log is a
         * 256 KiB ring and this panel writes to it every two seconds.
         *
         * <p>Never null and never contains a space, so it survives the greps
         * that count {@code ping=} lines (T5.2, T5.3, T5.6).
         */
        public final String detail;

        Cycle(String failure, boolean moved, String host, boolean idle, String detail) {
            this.failure = failure;
            this.moved = moved;
            this.host = host;
            this.idle = idle;
            this.detail = detail;
        }
    }

    /**
     * Pure: one probe failure, shortened to a single token for the heartbeat.
     *
     * <p>A probe failure is an exception's {@code toString()} — class, colon,
     * and a sentence naming both addresses and the timeout, or the class on
     * its own when the exception carries no message. Printed whole,
     * once per offline cycle, two hosts of that would be most of the log. The
     * class alone is what tells the failures apart that have to be told apart:
     * {@code ConnectException} is a PC that is not listening, {@code
     * SocketTimeoutException} is a firewall dropping rather than refusing
     * (the trap in {@code docs/SERVER-SETUP.md}), {@code HTTP-401} is a key
     * the panel does not have. The whole text still goes out once per
     * transition, in {@code PcPoller.deliver}.
     *
     * @return a token with no whitespace in it, so the line stays greppable
     */
    public static String shortReason(String failure) {
        if (failure == null || failure.isEmpty()) {
            return "none";
        }
        String head = failure;
        int colon = head.indexOf(':');
        // A dotted prefix before the colon is a class name: drop the message.
        // "HTTP 500" has no colon and stays whole.
        if (colon > 0 && head.lastIndexOf('.', colon) > 0) {
            head = head.substring(0, colon);
        }
        // Then the package, in a second step rather than inside the branch
        // above: Throwable.toString() omits the colon entirely when the
        // exception carries no message, and PcPoller.probe stores exactly that
        // string ("toString(), not getMessage(), so a class with no message
        // still says something"). Stripping only on the colon left those as
        // "java.net.SocketTimeoutException" -- and anything longer, such as a
        // bare SSLHandshakeException, chopped mid-word by MAX_REASON.
        // Guarded so a head with a space ("HTTP 500") or a trailing dot is
        // left alone: only a dotted, space-free token is a class name.
        int dot = head.lastIndexOf('.');
        if (dot > 0 && dot < head.length() - 1
                && head.matches("\\S+") && head.indexOf(':') < 0) {
            head = head.substring(dot + 1);
        }
        head = head.trim().replaceAll("\\s+", "-");
        if (head.isEmpty()) {
            return "none";
        }
        return head.length() > MAX_REASON ? head.substring(0, MAX_REASON) : head;
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
        // The same failures again, one token per host, for the line that is
        // written every cycle rather than once per transition.
        StringBuilder brief = new StringBuilder("hosts=");
        String idleHost = null;
        for (String host : probeOrder()) {
            if (stopped.now()) {
                break;
            }
            String failure = prober.probe(host);
            if (failure == null) {
                return new Cycle(null, answered(host), host, false, "host=" + host);
            }
            if (DISPLAY_OFF.equals(failure)) {
                if (idleHost == null) {
                    idleHost = host;
                }
                continue;
            }
            if (failures.length() > 0) {
                failures.append("; ");
                brief.append(',');
            }
            failures.append(host).append(": ").append(failure);
            brief.append(host).append(':').append(shortReason(failure));
        }
        if (idleHost != null) {
            // The idle host is named the same way an online one is: which PC
            // the panel is on is the question, and a dark panel is when it is
            // asked.
            return new Cycle(null, answered(idleHost), idleHost, true, "host=" + idleHost);
        }
        return new Cycle(failures.length() > 0 ? failures.toString() : "not attempted",
                false, null, false,
                failures.length() > 0 ? brief.toString() : "hosts=not-attempted");
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
