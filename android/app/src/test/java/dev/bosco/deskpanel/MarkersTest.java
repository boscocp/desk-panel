package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * The markers are a contract with {@code e2e/run_e2e.py} and with the table in
 * {@code docs/TESTING.md}, so they are asserted literally: every expected value
 * below is written out by hand rather than derived from {@link Markers}, which
 * is the only way a test can notice a rename. A test that built the string the
 * same way the production code does would agree with any typo.
 *
 * <p>This is what {@link Markers} having no Android imports buys — the contract
 * is checkable by {@code ./gradlew test} on the JVM, with no device.
 */
public class MarkersTest {

    @Test
    public void tagIsTheOneLogcatFilter() {
        assertEquals("DeskPanel", Markers.TAG);
    }

    @Test
    public void stateMarkers() {
        assertEquals("state=online", Markers.state(true));
        assertEquals("state=offline", Markers.state(false));
    }

    @Test
    public void screenMarkers() {
        assertEquals("screen=wake", Markers.screen(true));
        assertEquals("screen=sleep", Markers.screen(false));
    }

    @Test
    public void thermalMarkersAreNotTheScreenMarkers() {
        assertEquals("screen=thermal", Markers.thermal(true));
        assertEquals("screen=thermal-clear", Markers.thermal(false));
        // Asserted rather than assumed: the E2E greps `screen=thermal`, and a
        // substring collision with `screen=thermal-clear` would make the
        // blanking assertion pass on a panel that had just come back. The suite
        // has to match on the whole line for this pair, and this is where that
        // requirement is visible.
        assertTrue(Markers.thermal(false).startsWith(Markers.thermal(true)));
    }

    @Test
    public void nightMarkers() {
        assertEquals("night=on", Markers.night(true));
        assertEquals("night=off", Markers.night(false));
    }

    @Test
    public void dormantMarkers() {
        assertEquals("dormant=on", Markers.dormant(true));
        assertEquals("dormant=off", Markers.dormant(false));
    }

    @Test
    public void heartbeatMarkers() {
        assertEquals("tick=1758240000", Markers.tick(1758240000L));
        assertEquals("ping=ok", Markers.ping("ok"));
        assertEquals("data=ok", Markers.data(true));
        assertEquals("data=err", Markers.data(false));
        assertEquals("battery=87", Markers.battery(87));
    }
}
