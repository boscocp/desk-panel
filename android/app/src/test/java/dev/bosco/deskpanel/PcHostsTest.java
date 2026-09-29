package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;

import org.junit.Test;

/** ADR 0016: more than one PC, on the JVM. */
public class PcHostsTest {

    private static final String WIN = "192.168.1.100";
    private static final String MAC = "192.168.1.101";

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
        assertThrows(IllegalArgumentException.class, () -> hosts.answered("10.0.0.1"));
        assertEquals(WIN, hosts.active());
    }

    @Test
    public void theListCannotBeChangedFromOutside() {
        PcHosts hosts = PcHosts.parse(WIN + "," + MAC);
        assertThrows(UnsupportedOperationException.class, () -> hosts.all().add("10.0.0.1"));
    }
}
