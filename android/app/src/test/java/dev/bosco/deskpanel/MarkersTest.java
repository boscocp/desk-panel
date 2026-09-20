package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;

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
        // These two are not the screen= pair, and that distinction is the whole
        // reason they exist: dark because the PC went away, against dark
        // because the device is cooking (ADR 0012).
        assertNotEquals(Markers.screen(false), Markers.thermal(true));

        // Note for whoever greps these: as spelled above, "screen=thermal" is a
        // *prefix* of "screen=thermal-clear", so an unanchored `grep -q` for
        // the blanking marker also matches the line saying the panel came back.
        // Every assertion anchors the end of the line. That is deliberately not
        // asserted here — a test pinning the collision would make renaming the
        // pair to something without it look like a regression, which is exactly
        // backwards.
    }

    @Test
    public void everyMarkerIsOneLineWithNoSpaces() {
        // The suite matches these against whole logcat lines, so a space would
        // make an anchored grep silently stop matching.
        for (String marker : new String[] {
                Markers.state(true), Markers.screen(true), Markers.thermal(true),
                Markers.thermal(false), Markers.night(true), Markers.dormant(true),
                Markers.ping("ok"), Markers.data(true), Markers.battery(87),
                Markers.tick(1758240000L)}) {
            assertEquals(marker, marker.trim());
            assertEquals(-1, marker.indexOf(' '));
        }
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
