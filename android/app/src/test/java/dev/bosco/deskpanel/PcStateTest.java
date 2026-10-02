package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * Runs on the JVM, in a second, with no device and no emulator. Nothing here
 * sleeps: {@link PcState#nextIntervalMs()} returns a number and the tests
 * assert on the number. Time is handed in, so a 15-second backoff costs
 * nothing to assert.
 */
public class PcStateTest {

    private static final long T0 = 1_000_000L;

    // --- before the first probe ------------------------------------------

    @Test
    public void startsUnknownSoTheFirstResultIsAlwaysATransition() {
        PcState s = new PcState();
        assertEquals(PcState.State.UNKNOWN, s.state());
        assertFalse(s.isOnline());
        assertFalse(s.transitioned());
        assertEquals(0, s.consecutiveFailures());
    }

    @Test
    public void probeIsDueImmediatelyBeforeTheFirstOne() {
        PcState s = new PcState();
        assertTrue(s.isDue(T0));
        assertTrue(s.isDue(Long.MIN_VALUE));
    }

    // --- the first result each way ---------------------------------------

    @Test
    public void firstSuccessGoesOnlineAndReportsTheTransition() {
        PcState s = new PcState();
        assertTrue(s.record(true, T0));
        assertTrue(s.transitioned());
        assertEquals(PcState.State.ONLINE, s.state());
        assertTrue(s.isOnline());
        assertEquals(0, s.consecutiveFailures());
        assertEquals(2000L, s.nextIntervalMs());
    }

    @Test
    public void firstFailureGoesOfflineAndReportsTheTransition() {
        PcState s = new PcState();
        assertTrue(s.record(false, T0));
        assertTrue(s.transitioned());
        assertEquals(PcState.State.OFFLINE, s.state());
        assertFalse(s.isOnline());
        assertEquals(1, s.consecutiveFailures());
        assertEquals(2000L, s.nextIntervalMs());
    }

    // --- transitions fire exactly once -----------------------------------
    // The case most likely to be wrong. A machine that reports a transition on
    // every poll spams the log and retoggles the screen; these fail it.

    @Test
    public void repeatedSuccessesReportNoFurtherTransition() {
        PcState s = new PcState();
        s.record(true, T0);
        for (int i = 1; i <= 5; i++) {
            assertFalse("success #" + (i + 1) + " must not re-transition",
                    s.record(true, T0 + i * 2000L));
            assertFalse(s.transitioned());
            assertEquals(PcState.State.ONLINE, s.state());
        }
    }

    @Test
    public void repeatedFailuresReportNoFurtherTransition() {
        PcState s = new PcState();
        s.record(false, T0);
        for (int i = 1; i <= 5; i++) {
            assertFalse("failure #" + (i + 1) + " must not re-transition",
                    s.record(false, T0 + i * 2000L));
            assertFalse(s.transitioned());
            assertEquals(PcState.State.OFFLINE, s.state());
        }
    }

    @Test
    public void everyFlipReportsATransitionAndEveryRepeatDoesNot() {
        // A machine that is stuck in one state fails the flips; a machine that
        // flaps fails the repeats. Both are caught by the same sequence. Going
        // offline from online takes two failures (ONLINE_GRACE_FAILURES), so
        // the falling edges land on the second one, and the lone failure at
        // index 10 is ridden out.
        boolean[] probes = {true, true, false, false, false, true, true, false, false, true,
                false, true};
        boolean[] expected = {true, false, false, true, false, true, false, false, true, true,
                false, false};

        PcState s = new PcState();
        for (int i = 0; i < probes.length; i++) {
            assertEquals("probe " + i, expected[i], s.record(probes[i], T0 + i * 1000L));
        }
        assertEquals(PcState.State.ONLINE, s.state());
    }

    @Test
    public void transitionFlagIsNotStickyAcrossPolls() {
        PcState s = new PcState();
        s.record(false, T0);
        assertTrue(s.transitioned());
        s.record(false, T0 + 2000L);
        assertFalse("transitioned() must describe the last probe only", s.transitioned());
    }

    // --- one late answer is not a logout (T4.7) ---------------------------

    @Test
    public void oneFailureWhileOnlineIsRiddenOut() {
        PcState s = new PcState();
        s.record(true, T0);
        assertFalse("no transition on the first failure", s.record(false, T0 + 2000L));
        assertEquals(PcState.State.ONLINE, s.state());
        assertTrue(s.isOnline());
        assertEquals("the failure is still counted", 1, s.consecutiveFailures());
        assertEquals("and the retry is the backoff's, not the cadence's",
                PcState.BACKOFF_BASE_MS, s.nextIntervalMs());
    }

    @Test
    public void theSecondFailureInARowGoesOffline() {
        PcState s = new PcState();
        s.record(true, T0);
        s.record(false, T0 + 2000L);
        assertTrue(s.record(false, T0 + 4000L));
        assertEquals(PcState.State.OFFLINE, s.state());
        assertEquals(2, s.consecutiveFailures());
    }

    @Test
    public void aSuccessBetweenFailuresResetsTheGrace() {
        // The game-loading pattern: a late answer every few polls. None of
        // them may darken the screen.
        PcState s = new PcState();
        s.record(true, T0);
        long now = T0;
        for (int i = 0; i < 20; i++) {
            now += 2000L;
            assertFalse("late answer " + i, s.record(false, now));
            now += 2000L;
            assertFalse("recovery " + i, s.record(true, now));
            assertEquals(PcState.State.ONLINE, s.state());
        }
    }

    @Test
    public void theGraceIsOnlyForOnline() {
        // From UNKNOWN, a phone booting beside a PC that is off must not light.
        PcState fresh = new PcState();
        assertTrue(fresh.record(false, T0));
        assertEquals(PcState.State.OFFLINE, fresh.state());

        // From IDLE the screen is already dark; offline is the truer state.
        PcState idle = new PcState();
        idle.record(true, true, T0);
        assertTrue(idle.record(false, T0 + 2000L));
        assertEquals(PcState.State.OFFLINE, idle.state());
    }

    @Test
    public void graceIsOneFailure() {
        assertEquals(1, PcState.ONLINE_GRACE_FAILURES);
    }

    // --- the backoff ladder ----------------------------------------------

    @Test
    public void offlineBackoffDoublesThenSticksAtTheCap() {
        PcState s = new PcState();
        long[] expected = {2000L, 4000L, 8000L, 15000L, 15000L, 15000L, 15000L, 15000L};
        long now = T0;
        for (int i = 0; i < expected.length; i++) {
            s.record(false, now);
            assertEquals("after " + (i + 1) + " consecutive failures",
                    expected[i], s.nextIntervalMs());
            assertEquals(i + 1, s.consecutiveFailures());
            now += s.nextIntervalMs();
        }
    }

    @Test
    public void backoffNeverExceedsTheCapEvenAfterAnOvernightOutage() {
        PcState s = new PcState();
        long now = T0;
        for (int i = 0; i < 5000; i++) {
            s.record(false, now);
            long interval = s.nextIntervalMs();
            assertTrue("interval " + interval + " exceeded the cap",
                    interval <= 15000L);
            assertTrue("interval " + interval + " below the base",
                    interval >= 2000L);
            now += interval;
        }
        assertEquals(15000L, s.nextIntervalMs());
    }

    @Test
    public void onlineCadenceIsFlatAtTwoSeconds() {
        PcState s = new PcState();
        long now = T0;
        for (int i = 0; i < 10; i++) {
            s.record(true, now);
            assertEquals(2000L, s.nextIntervalMs());
            now += 2000L;
        }
    }

    // --- recovery ---------------------------------------------------------

    @Test
    public void firstSuccessAfterDeepBackoffResetsTheCadence() {
        PcState s = new PcState();
        long now = T0;
        for (int i = 0; i < 10; i++) {
            s.record(false, now);
            now += s.nextIntervalMs();
        }
        assertEquals(15000L, s.nextIntervalMs());
        assertEquals(10, s.consecutiveFailures());

        assertTrue("recovery is a transition", s.record(true, now));
        assertEquals(PcState.State.ONLINE, s.state());
        assertEquals(0, s.consecutiveFailures());
        assertEquals("a success must drop straight back to the online cadence",
                2000L, s.nextIntervalMs());
    }

    @Test
    public void aSingleSuccessInTheMiddleOfAnOutageRestartsTheLadderFromTheBase() {
        PcState s = new PcState();
        s.record(false, T0);
        s.record(false, T0 + 2000L);
        s.record(false, T0 + 6000L);
        assertEquals(8000L, s.nextIntervalMs());

        s.record(true, T0 + 14000L);
        s.record(false, T0 + 16000L);
        assertEquals("the ladder must restart, not resume",
                2000L, s.nextIntervalMs());
        assertEquals(1, s.consecutiveFailures());
    }

    // --- scheduling, so the poller keeps no state of its own ---------------

    @Test
    public void nextProbeIsTheProbeTimePlusTheInterval() {
        PcState s = new PcState();
        s.record(true, T0);
        assertEquals(T0 + 2000L, s.nextProbeAtMs());

        s.record(false, T0 + 2000L);
        assertEquals(T0 + 4000L, s.nextProbeAtMs());

        s.record(false, T0 + 4000L);
        assertEquals("second failure waits 4s", T0 + 8000L, s.nextProbeAtMs());
    }

    @Test
    public void probeIsDueOnlyOnceTheIntervalHasElapsed() {
        PcState s = new PcState();
        s.record(true, T0);
        assertFalse(s.isDue(T0));
        assertFalse(s.isDue(T0 + 1999L));
        assertTrue("due exactly on the deadline", s.isDue(T0 + 2000L));
        assertTrue(s.isDue(T0 + 60000L));
    }

    @Test
    public void theDeadlineStretchesWithTheBackoff() {
        PcState s = new PcState();
        s.record(false, T0);
        s.record(false, T0 + 2000L);
        s.record(false, T0 + 6000L);
        // Three failures: 8s, not 2s.
        assertFalse(s.isDue(T0 + 6000L + 7999L));
        assertTrue(s.isDue(T0 + 6000L + 8000L));
    }

    // --- Dormancy: offline and on battery (T5.6) ----------------------------
    //
    // The state where the schedule leaves this process entirely. Worth testing
    // on the JVM precisely because it is impossible to observe on the device
    // without waiting fifteen minutes for the alarm that replaces it.

    @Test
    public void offlineOnBatteryIsDormant() {
        PcState s = new PcState();
        s.record(false, T0);

        assertTrue(s.isDormant(false));
    }

    @Test
    public void offlineOnMainsIsNotDormant() {
        // The ADR 0014 arrangement, unchanged: a wake lock and the ladder, on a
        // phone that is charging anyway.
        PcState s = new PcState();
        s.record(false, T0);

        assertFalse(s.isDormant(true));
    }

    @Test
    public void onlineIsNeverDormantWhateverThePower() {
        // Somebody is looking at the panel and FLAG_KEEP_SCREEN_ON is holding
        // the device up for the display's sake, so a 2s probe is the cheapest
        // thing happening. Going sparse here would make the panel stale on
        // screen to save nothing.
        PcState s = new PcState();
        s.record(true, T0);

        assertFalse(s.isDormant(true));
        assertFalse(s.isDormant(false));
    }

    @Test
    public void unknownIsNotDormantBeforeTheFirstProbe() {
        // Nothing has been learned yet, and the first probe has to happen for
        // anything else to. Dormancy here would mean never probing at all.
        PcState s = new PcState();

        assertFalse(s.isDormant(false));
        assertFalse(s.isDormant(true));
    }

    @Test
    public void dormancyFollowsTheStateAndNotTheFailureCount() {
        // Dormancy follows OFFLINE, not a failure count: there is no "deeply
        // offline" threshold to cross, because the cost being avoided is the
        // wake lock. From UNKNOWN one failure is OFFLINE; from ONLINE it takes
        // two (ONLINE_GRACE_FAILURES), which the second half shows.
        PcState s = new PcState();
        s.record(false, T0);
        assertTrue(s.isDormant(false));

        s.record(true, T0 + 2000L);
        assertFalse("one success is enough to leave dormancy", s.isDormant(false));

        s.record(false, T0 + 4000L);
        assertFalse("one failure from online is ridden out", s.isDormant(false));
        s.record(false, T0 + 6000L);
        assertTrue(s.isDormant(false));
    }

    @Test
    public void theSparseAlarmIsAboveTheFloorDozeImposes() {
        // Doze clamps an allow-while-idle alarm to roughly nine minutes, so a
        // tighter interval would be a promise the platform does not keep. This
        // asserts the number stays on the right side of that.
        assertTrue("an allow-while-idle alarm below ~9 minutes is not honoured",
                PcState.DORMANT_ALARM_MS >= 9 * 60 * 1000L);
    }

    // --- the display (ADR 0020) --------------------------------------------

    @Test
    public void anAnswerWithTheDisplayOffIsIdleAndNotOnline() {
        PcState s = new PcState();
        s.record(true, T0);
        assertTrue(s.record(true, true, T0 + 2000));
        assertEquals(PcState.State.IDLE, s.state());
        assertFalse(s.isOnline());
    }

    @Test
    public void idleKeepsTheOnlineCadenceSoTheMonitorIsNoticedWithinOnePoll() {
        PcState s = new PcState();
        s.record(false, T0);
        s.record(false, T0 + 2000);
        s.record(true, true, T0 + 6000);
        assertEquals(0, s.consecutiveFailures());
        assertEquals(PcState.ONLINE_INTERVAL_MS, s.nextIntervalMs());
        for (int i = 1; i <= 20; i++) {
            s.record(true, true, T0 + 6000 + i * 2000L);
        }
        assertEquals(PcState.ONLINE_INTERVAL_MS, s.nextIntervalMs());
    }

    @Test
    public void theDisplayComingBackIsATransitionToOnline() {
        PcState s = new PcState();
        s.record(true, true, T0);
        assertTrue(s.record(true, false, T0 + 2000));
        assertEquals(PcState.State.ONLINE, s.state());
        assertFalse(s.record(true, false, T0 + 4000));
    }

    @Test
    public void anUnreachablePcIsOfflineWhateverItsDisplaySaid() {
        PcState s = new PcState();
        s.record(false, true, T0);
        assertEquals(PcState.State.OFFLINE, s.state());
    }

    @Test
    public void idleOnBatteryIsDormantAndOnMainsIsNot() {
        PcState s = new PcState();
        s.record(true, true, T0);
        assertTrue(s.isDormant(false));
        assertFalse(s.isDormant(true));
    }
}
