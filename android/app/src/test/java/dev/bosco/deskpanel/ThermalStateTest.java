package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * The hysteresis, driven in both directions on the JVM. Warming a real phone
 * from 38 to 45 degrees and back takes most of an afternoon and cannot be made
 * to land on the exact values that matter; here it is four method calls.
 *
 * <p>The test that carries the task is
 * {@link #holdsTheBlankingVerdictOnTheWayBackDown()}: a single-threshold
 * implementation passes every other test in this file, because every other test
 * walks the temperature in one direction only.
 */
public class ThermalStateTest {

    /** Any monotonic value; the class documents that it ignores this. */
    private static final long T0 = 1_000_000L;

    // --- before the first reading ----------------------------------------

    @Test
    public void startsPaintingSoThePanelCanBootBeforeTheFirstBroadcast() {
        ThermalState s = new ThermalState();
        assertFalse(s.isTooHot());
        assertFalse(s.transitioned());
    }

    // --- the thresholds themselves ---------------------------------------

    @Test
    public void blanksAtTheThreshold() {
        ThermalState s = new ThermalState();
        assertTrue(s.record(ThermalState.BLANK_AT_C, T0));
        assertTrue(s.isTooHot());
    }

    @Test
    public void doesNotBlankJustUnderIt() {
        ThermalState s = new ThermalState();
        assertFalse(s.record(44.9, T0));
        assertFalse(s.isTooHot());
    }

    @Test
    public void clearsAtTheLowerThreshold() {
        ThermalState s = new ThermalState();
        s.record(46.0, T0);
        assertTrue(s.record(ThermalState.CLEAR_AT_C, T0 + 1));
        assertFalse(s.isTooHot());
    }

    // --- the point of the class ------------------------------------------

    @Test
    public void holdsTheBlankingVerdictOnTheWayBackDown() {
        ThermalState s = new ThermalState();
        s.record(45.2, T0);
        assertTrue(s.isTooHot());

        // 40 is under the blanking threshold and well under it, and a naive
        // implementation with one line at 45 clears here. It must not: the
        // screen is the heat source, so coming back at 40 means climbing to 45
        // again within minutes, for as long as the room stays warm.
        assertFalse("40 degrees on the way down must not clear the verdict",
                s.record(40.0, T0 + 1));
        assertTrue(s.isTooHot());

        assertFalse(s.record(38.5, T0 + 2));
        assertTrue(s.isTooHot());

        assertTrue(s.record(37.9, T0 + 3));
        assertFalse(s.isTooHot());
    }

    @Test
    public void holdsThePaintingVerdictOnTheWayUp() {
        ThermalState s = new ThermalState();
        assertFalse(s.record(30.0, T0));
        assertFalse(s.record(38.0, T0 + 1));
        assertFalse(s.record(41.0, T0 + 2));
        assertFalse(s.record(44.0, T0 + 3));
        assertFalse(s.isTooHot());
        assertTrue(s.record(45.0, T0 + 4));
        assertTrue(s.isTooHot());
    }

    @Test
    public void aFullCycleTransitionsExactlyTwice() {
        ThermalState s = new ThermalState();
        int transitions = 0;
        for (double t : new double[] {31.0, 39.0, 42.0, 45.5, 46.0, 43.0, 39.0, 37.0, 33.0}) {
            if (s.record(t, T0)) {
                transitions++;
            }
        }
        assertEquals("one blank and one clear, whatever the readings in between",
                2, transitions);
        assertFalse(s.isTooHot());
    }

    // --- the readings that are not readings -------------------------------

    @Test
    public void aNaNHoldsTheVerdictRatherThanClearingIt() {
        ThermalState s = new ThermalState();
        s.record(46.0, T0);
        assertFalse(s.record(Double.NaN, T0 + 1));
        assertTrue("a sensor that stopped answering is not evidence of cooling",
                s.isTooHot());
    }

    @Test
    public void transitionedIsStickyOnlyUntilTheNextReading() {
        ThermalState s = new ThermalState();
        assertTrue(s.record(46.0, T0));
        assertTrue(s.transitioned());
        assertFalse(s.record(46.1, T0 + 1));
        assertFalse("a steady blanked state must log nothing", s.transitioned());
    }
}
