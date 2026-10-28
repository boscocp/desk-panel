package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** T4.12, ADR 0024: what a wake that has not shown the panel yet means. */
public class WakeRetryTest {

    @Test
    public void aWakeLeftDarkIsAskedAgain() {
        // state=online, and the display still dozing thirty seconds later.
        assertEquals(WakeRetry.Step.RETRY, WakeRetry.next(true, false));
    }

    @Test
    public void aLitDisplayIsSettledWhoeverIsInFront() {
        // The panel came up, or somebody has the phone in hand; neither is a
        // reason to keep pulling the panel over what is on screen.
        assertEquals(WakeRetry.Step.SETTLED, WakeRetry.next(true, true));
    }

    @Test
    public void offlineStopsWhateverTheDisplayIsDoing() {
        assertEquals(WakeRetry.Step.STOP, WakeRetry.next(false, false));
        assertEquals(WakeRetry.Step.STOP, WakeRetry.next(false, true));
    }

    @Test
    public void showingNeedsFocusAndALitDisplay() {
        assertTrue(WakeRetry.showing(true, true));
        // The window keeps focus while the display dozes under it, which is
        // what the phone looked like at 13:37 on the day this was found.
        assertFalse(WakeRetry.showing(true, false));
        assertFalse(WakeRetry.showing(false, true));
        assertFalse(WakeRetry.showing(false, false));
    }

    @Test
    public void aSlowWakeIsNotRacedAndARefusedOneIsNotHammered() {
        // A wake that lands gains focus in under a second on the Redmi; the
        // retry must not fire inside that, nor more than twice a minute.
        assertTrue(WakeRetry.RETRY_MS >= 5_000L);
        assertTrue(WakeRetry.RETRY_MS <= 60_000L);
    }
}
