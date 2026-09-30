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
        assertEquals("state=online", Markers.state(PcState.State.ONLINE));
        assertEquals("state=offline", Markers.state(PcState.State.OFFLINE));
        assertEquals("state=idle", Markers.state(PcState.State.IDLE));
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
                Markers.state(true), Markers.state(PcState.State.IDLE),
                Markers.screen(true), Markers.thermal(true),
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
    public void actionMarkers() {
        // Written out by hand, like every other expected value in this file:
        // e2e/run_e2e.py and T8.2's own acceptance grep for these strings.
        assertEquals("action=mute-audio result=ok", Markers.action("mute-audio", "ok"));
        assertEquals("action=mute-mic result=err", Markers.action("mute-mic", "err"));
        assertEquals("action=mute-mic result=offline", Markers.action("mute-mic", "offline"));
        assertEquals("action=shutdown result=rejected", Markers.action("shutdown", "rejected"));
    }

    @Test
    public void theActionMarkerCarriesWhichButtonWasPressed() {
        // Two buttons sit next to each other and a mis-tap is the failure the
        // 56px target exists to prevent. That is only checkable if the log
        // says which one was actually sent, so the two must differ.
        assertNotEquals(Markers.action("mute-audio", "ok"), Markers.action("mute-mic", "ok"));
    }

    @Test
    public void aRejectedIdCannotForgeASecondMarkerLine() {
        // The refusal paths log the string the page handed over, which is the
        // only evidence there is that a theme asked for something. A newline
        // in it would let the page write its own `action=... result=ok` into
        // logcat, and that is what every E2E assertion here reads (ADR 0009).
        assertEquals("action=x.action=mute-audio result=ok result=rejected",
                Markers.action("x\naction=mute-audio result=ok", "rejected"));
        assertEquals("action=a.b result=rejected", Markers.action("a\rb", "rejected"));
        assertEquals("action=null result=offline", Markers.action(null, "offline"));
    }

    @Test
    public void heartbeatMarkers() {
        assertEquals("tick=1758240000", Markers.tick(1758240000L));
        assertEquals("ping=ok", Markers.ping("ok"));
        assertEquals("data=ok", Markers.data(true));
        assertEquals("data=err", Markers.data(false));
        assertEquals("spectrum=open", Markers.spectrum("open"));
        assertEquals("spectrum=off", Markers.spectrum("off"));
        assertEquals("battery=87", Markers.battery(87));
    }
}
