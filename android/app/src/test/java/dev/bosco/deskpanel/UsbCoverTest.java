package dev.bosco.deskpanel;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** T4.15: a panel covered at a USB connect was covered by MIUI's chooser. */
public class UsbCoverTest {

    private static final long T = 1_000_000L;

    @Test
    public void aCoverJustAfterTheConnectIsTheChooser() {
        // 2026-11-26 09:02:06: USB_STATE configured, the chooser 13 ms later.
        assertTrue(UsbCover.reclaim(true, T + 500, T));
    }

    @Test
    public void theBroadcastMayArriveAfterTheCover() {
        assertTrue(UsbCover.reclaim(true, T, T + 300));
    }

    @Test
    public void theWindowIsInclusiveAndEndsThere() {
        assertTrue(UsbCover.reclaim(true, T + UsbCover.WINDOW_MS, T));
        assertFalse(UsbCover.reclaim(true, T + UsbCover.WINDOW_MS + 1, T));
        assertFalse(UsbCover.reclaim(true, T, T + UsbCover.WINDOW_MS + 1));
    }

    @Test
    public void anAppOpenedLongBeforeTheConnectIsLeftAlone() {
        // Somebody using the phone when the switch moves: their app stays.
        assertFalse(UsbCover.reclaim(true, T, T + 60_000));
    }

    @Test
    public void offlineThereIsNothingToGiveBack() {
        assertFalse(UsbCover.reclaim(false, T, T));
    }

    @Test
    public void neverCoveredOrNeverConnectedIsNoReclaim() {
        // Also the state after a reclaim: PanelService zeroes both times, so a
        // second cover inside the window is left alone.
        assertFalse(UsbCover.reclaim(true, 0, T));
        assertFalse(UsbCover.reclaim(true, T, 0));
    }
}
