package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.junit.Test;

/** ADR 0016: more than one PC, on the JVM. */
public class PcHostsTest {

    private static final String WIN = "pc-windows";
    private static final String MAC = "pc-mac";
    private static final String THIRD = "pc-third";

    /** Records every host dialled, answering only for {@code up}. */
    private static PcHosts.Prober answering(List<String> dialled, String... up) {
        List<String> live = Arrays.asList(up);
        return host -> {
            dialled.add(host);
            return live.contains(host) ? null : "java.net.ConnectException";
        };
    }

    private static final PcHosts.Stopped RUNNING = () -> false;

    @Test
    public void aCycleAsksTheActiveHostFirstAndStopsAtTheFirstAnswer() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        hosts.answered(MAC);
        List<String> dialled = new ArrayList<>();
        PcHosts.Cycle cycle = hosts.cycle(answering(dialled, WIN, MAC), RUNNING);
        assertEquals(Arrays.asList(MAC), dialled);
        assertEquals(null, cycle.failure);
        assertFalse(cycle.moved);
    }

    @Test
    public void whenTheActiveHostGoesTheNextOneThatAnswersTakesOver() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        List<String> dialled = new ArrayList<>();
        PcHosts.Cycle cycle = hosts.cycle(answering(dialled, MAC), RUNNING);
        assertEquals(Arrays.asList(WIN, MAC), dialled);
        assertTrue(cycle.moved);
        assertEquals(MAC, cycle.host);
        assertEquals(MAC, hosts.active());
    }

    @Test
    public void noAnswerAnywhereNamesEveryHostAndMovesNothing() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        List<String> dialled = new ArrayList<>();
        PcHosts.Cycle cycle = hosts.cycle(answering(dialled), RUNNING);
        assertEquals(Arrays.asList(WIN, MAC), dialled);
        assertTrue(cycle.failure.contains(WIN) && cycle.failure.contains(MAC));
        assertEquals(WIN, hosts.active());
    }

    @Test
    public void aStoppedLoopDialsNothingMore() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        List<String> dialled = new ArrayList<>();
        int[] asked = {0};
        PcHosts.Cycle cycle = hosts.cycle(answering(dialled, MAC), () -> asked[0]++ > 0);
        assertEquals(Arrays.asList(WIN), dialled);
        assertEquals(WIN, hosts.active());
        assertTrue(cycle.failure != null);
    }

    @Test
    public void moreHostsThanTheWakeLockCoversAreRefused() {
        PcHosts.parse(WIN + "," + MAC + "," + THIRD);
        assertThrows(IllegalArgumentException.class,
                () -> PcHosts.parse(WIN + "," + MAC + "," + THIRD + ",pc-fourth"));
    }

    @Test
    public void oneHostIsTheOldBehaviourExactly() {
        PcHosts hosts = PcHosts.parse(WIN);
        assertEquals(Arrays.asList(WIN), hosts.all());
        assertEquals(WIN, hosts.active());
        assertEquals(Arrays.asList(WIN), hosts.probeOrder());
    }

    @Test
    public void aListIsReadInOrderWithBlanksAndRepeatsDropped() {
        PcHosts hosts = PcHosts.parse(" " + WIN + " ,, " + MAC + "," + WIN + ",");
        assertEquals(Arrays.asList(WIN, MAC), hosts.all());
        assertEquals(WIN, hosts.active());
    }

    @Test
    public void nothingConfiguredFailsLoudlyRatherThanReportingOfflineForEver() {
        assertThrows(IllegalArgumentException.class, () -> PcHosts.parse(""));
        assertThrows(IllegalArgumentException.class, () -> PcHosts.parse(" , "));
        assertThrows(IllegalArgumentException.class, () -> PcHosts.parse(null));
    }

    @Test
    public void theHostThatAnsweredIsAskedFirstNextTime() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        assertTrue(hosts.answered(MAC));
        assertEquals(MAC, hosts.active());
        assertEquals(Arrays.asList(MAC, WIN), hosts.probeOrder());
    }

    @Test
    public void answeringAgainIsNotAMove() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        assertFalse(hosts.answered(WIN));
        assertTrue(hosts.answered(MAC));
        assertFalse(hosts.answered(MAC));
    }

    @Test
    public void aHostOutsideThePinIsRefused() {
        PcHosts hosts = PcHosts.parse(WIN);
        assertThrows(IllegalArgumentException.class, () -> hosts.answered("pc-unlisted"));
        assertEquals(WIN, hosts.active());
    }

    @Test
    public void theListCannotBeChangedFromOutside() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        assertThrows(UnsupportedOperationException.class, () -> hosts.all().add("pc-unlisted"));
    }

    // --- the display (ADR 0020) --------------------------------------------

    /** Answers as {@code answering} does, but idle for the hosts in {@code dark}. */
    private static PcHosts.Prober withDark(List<String> dialled, List<String> up, String... dark) {
        List<String> idle = Arrays.asList(dark);
        return host -> {
            dialled.add(host);
            if (idle.contains(host)) {
                return PcHosts.DISPLAY_OFF;
            }
            return up.contains(host) ? null : "java.net.ConnectException";
        };
    }

    @Test
    public void aDarkPcDoesNotEndTheCycleWhenAnotherHasSomebodyAtIt() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        List<String> dialled = new ArrayList<>();
        PcHosts.Cycle cycle = hosts.cycle(withDark(dialled, Arrays.asList(MAC), WIN), RUNNING);
        assertEquals(Arrays.asList(WIN, MAC), dialled);
        assertFalse(cycle.idle);
        assertEquals(null, cycle.failure);
        assertEquals(MAC, hosts.active());
    }

    @Test
    public void everyAnsweringPcDarkIsIdleOnTheActiveOne() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        hosts.answered(MAC);
        List<String> dialled = new ArrayList<>();
        PcHosts.Cycle cycle = hosts.cycle(
                withDark(dialled, Arrays.<String>asList(), WIN, MAC), RUNNING);
        assertTrue(cycle.idle);
        assertEquals(null, cycle.failure);
        assertEquals(MAC, cycle.host);
        assertFalse(cycle.moved);
    }

    @Test
    public void oneDarkPcAndOneGoneIsIdleNotOffline() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        PcHosts.Cycle cycle = hosts.cycle(
                withDark(new ArrayList<>(), Arrays.<String>asList(), MAC), RUNNING);
        assertTrue(cycle.idle);
        assertEquals(MAC, cycle.host);
        assertTrue(cycle.moved);
    }

    @Test
    public void onlyTheLiteralOffIsDisplayOff() {
        assertTrue(PcHosts.displayOff("{\"ok\": true, \"display\": \"off\"}"));
        assertFalse(PcHosts.displayOff("{\"ok\": true, \"display\": \"on\"}"));
        assertFalse(PcHosts.displayOff("{\"ok\": true, \"display\": \"unknown\"}"));
        assertFalse(PcHosts.displayOff("{\"ok\": true}"));
        assertFalse(PcHosts.displayOff("not json"));
        assertFalse(PcHosts.displayOff(null));
    }
}
