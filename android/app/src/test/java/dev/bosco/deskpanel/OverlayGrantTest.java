package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;

import org.json.JSONObject;
import org.junit.Test;

/** T4.15, ADR 0026: when a reading of "Display over other apps" is news. */
public class OverlayGrantTest {

    @Test
    public void aServiceThatStartsWithoutTheGrantSaysSo() {
        // The watchdog revival of 2026-11-16 16:19: the first reading is the
        // only chance to say it before the first dark wake.
        assertEquals(OverlayGrant.Change.LOST, OverlayGrant.change(null, false));
    }

    @Test
    public void aServiceThatStartsWithTheGrantSaysNothing() {
        assertEquals(OverlayGrant.Change.NONE, OverlayGrant.change(null, true));
    }

    @Test
    public void losingItIsOneLineAndKeepingItLostIsNone() {
        assertEquals(OverlayGrant.Change.LOST, OverlayGrant.change(true, false));
        assertEquals(OverlayGrant.Change.NONE, OverlayGrant.change(false, false));
    }

    @Test
    public void gettingItBackIsOneLineAndKeepingItIsNone() {
        assertEquals(OverlayGrant.Change.BACK, OverlayGrant.change(false, true));
        assertEquals(OverlayGrant.Change.NONE, OverlayGrant.change(true, true));
    }

    @Test
    public void aMissingGrantRidesTheBatteryObject() throws Exception {
        String battery = "{\"level\":50,\"tempC\":30,\"charging\":true}";
        JSONObject lost = new JSONObject(DataPayload.withOverlay(battery, false));
        assertEquals(false, lost.getBoolean("overlay"));
        assertEquals(50, lost.getInt("level"));
    }

    @Test
    public void aHeldGrantLeavesTheBatteryObjectAsItWas() {
        // The resting state adds nothing to the payload, so every test and
        // fixture written before T4.15 still describes what the page gets.
        String battery = "{\"level\":50,\"tempC\":30,\"charging\":true}";
        assertEquals(battery, DataPayload.withOverlay(battery, true));
    }

    @Test
    public void noBatteryYetStaysNoBattery() {
        assertEquals(null, DataPayload.withOverlay(null, false));
    }

    @Test
    public void aBatteryThatWillNotParseIsLeftAlone() {
        assertEquals("{not json", DataPayload.withOverlay("{not json", false));
    }

    @Test
    public void theMarkersAreTheOnesTheLogIsReadFor() {
        assertEquals("overlay=lost", Markers.overlayLost());
        assertEquals("overlay=back", Markers.overlayBack());
    }
}
