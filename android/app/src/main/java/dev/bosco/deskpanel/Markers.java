package dev.bosco.deskpanel;

/**
 * The logcat vocabulary, in one place (TT.6).
 *
 * <p>These strings are an API. {@code e2e/run_e2e.py} greps for them verbatim,
 * and {@code docs/TESTING.md} carries the table that is their specification.
 * Renaming one breaks the end-to-end suite, which is why the app reports its own
 * state at all: Android exposes no documented way to read screen state from adb
 * (ADR 0009).
 *
 * <p>Two kinds, and the distinction is the whole design. <b>Transitions</b> —
 * {@link #state}, {@link #screen}, {@link #thermal}, {@link #night},
 * {@link #dormant} — are
 * emitted only when something changes, so "exactly one marker" is a countable assertion and a
 * steady state logs nothing. <b>Heartbeats</b> — {@link #tick}, {@link #ping},
 * {@link #data}, {@link #battery} — are emitted per cycle at a bounded rate,
 * because "this is still running" and "at most four polls a minute" cannot be
 * asserted any other way.
 *
 * <p>No Android imports, deliberately. This class builds the strings and the
 * two call sites that own a transition log them — {@code PanelService} for
 * {@code state}, {@code MainActivity} for {@code screen} — rather than this
 * class calling {@code Log} itself. The rule in {@code android/CLAUDE.md} is
 * that anything worth testing lives in a plain class with no Android imports so
 * {@code ./gradlew test} covers it on the JVM, and a contract the E2E suite
 * greps for is exactly that: {@code MarkersTest} asserts every string here
 * without a device, which a class holding {@code Log.i} could not offer.
 *
 * <p>The property the acceptance actually enforces is that no marker string
 * exists anywhere else in {@code main/java} — that is what keeps the suite from
 * passing against a stale inline copy — and it holds either way.
 *
 * <p>Resist adding more. Five behaviours are covered; more is noise to grep
 * through.
 */
public final class Markers {

    /** The one logcat tag. {@code adb logcat -s DeskPanel} is the whole filter. */
    public static final String TAG = "DeskPanel";

    private Markers() {
    }

    /**
     * Whether the PC answered — which is to say, whether a human is logged in
     * (invariant 2). Logged by {@code PanelService} on transitions only.
     */
    public static String state(boolean online) {
        return online ? "state=online" : "state=offline";
    }

    /**
     * What the app asked the screen to do. It records the decision, not the
     * panel's actual brightness: proving the display really went dark is
     * eyes-only work and lives in T4.4's manual check.
     */
    public static String screen(boolean awake) {
        return awake ? "screen=wake" : "screen=sleep";
    }

    /**
     * The thermal authority blanking the panel, or giving it back (T5.5).
     *
     * <p>Deliberately not {@link #screen(boolean)}. Both put the panel dark and
     * the causes could not be further apart: {@code screen=sleep} means the PC
     * went away and is the product working, while {@code screen=thermal} means
     * the device is too hot to keep painting and the owner has a problem —
     * ventilation, sun, or a cell on its way to a bulge. Collapsing them would
     * make the panel's most expensive confusion unresolvable from the log, and
     * the log is the only screen-state signal this project trusts (ADR 0009).
     *
     * <p>The mechanisms differ too, which is the other half of why one string
     * cannot carry both: sleep releases {@code FLAG_KEEP_SCREEN_ON} and lets
     * Android take the display, thermal holds the window foreground at
     * brightness zero so it can bring the panel back by itself (ADR 0012).
     */
    public static String thermal(boolean blanking) {
        return blanking ? "screen=thermal" : "screen=thermal-clear";
    }

    /** The night profile crossing its schedule boundary (T6.4). */
    public static String night(boolean on) {
        return on ? "night=on" : "night=off";
    }

    /**
     * The clock is alive (T2.4). Once a minute, not once a second: the point is
     * survival over hours, and a per-second line would be log spam.
     *
     * @param epochSeconds seconds since the epoch, so two ticks can be
     *                     subtracted to get a real elapsed time
     */
    public static String tick(long epochSeconds) {
        return "tick=" + epochSeconds;
    }

    /**
     * One poll attempt (T5.3). This is the heartbeat the backoff assertions
     * count, so it fires per probe rather than per transition.
     */
    public static String ping(String outcome) {
        return "ping=" + outcome;
    }

    /** One data cycle (T5.1). */
    public static String data(boolean ok) {
        return ok ? "data=ok" : "data=err";
    }

    /**
     * Whether the poll loop has handed its schedule to {@code AlarmManager}
     * because the phone is offline and on its own battery (T5.6).
     *
     * <p>A transition marker, and the eighth string in a class whose javadoc
     * says to resist adding more — so here is the justification. Everything
     * else about dormancy is an <em>absence</em>: no {@code ping=} lines, no
     * wake lock, no {@code data=}. An absence cannot be told apart from a poll
     * loop that has silently died, which is precisely the failure T5.2 calls
     * the worst available, and the state lasts all night. This is the one line
     * that says the silence was deliberate.
     */
    public static String dormant(boolean on) {
        return on ? "dormant=on" : "dormant=off";
    }

    /** Battery level, on broadcast (T5.4). */
    public static String battery(int level) {
        return "battery=" + level;
    }
}
