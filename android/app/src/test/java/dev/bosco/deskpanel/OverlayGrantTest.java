package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;

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
}
