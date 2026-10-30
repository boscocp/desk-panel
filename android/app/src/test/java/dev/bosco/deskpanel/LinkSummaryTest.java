package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;

import java.util.Arrays;
import java.util.Collections;

import org.junit.Test;

/** T4.13: a failing ping line says where the phone itself is. */
public class LinkSummaryTest {

    @Test
    public void theAddressAndGatewayAreNamed() {
        assertEquals("self=10.0.4.7/24 gw=10.0.4.1",
                LinkSummary.describe(Arrays.asList("10.0.4.7/24"), "10.0.4.1"));
    }

    @Test
    public void ipv6AddressesAreLeftOut() {
        assertEquals("self=10.0.3.107/24 gw=10.0.3.1",
                LinkSummary.describe(Arrays.asList(
                        "fe80::8a46:4ff:fe29:7432/64", "10.0.3.107/24",
                        "fd85:5464:5fac:b629::7/64"), "10.0.3.1"));
    }

    @Test
    public void noNetworkIsSaidRatherThanLeftBlank() {
        assertEquals("self=none gw=none", LinkSummary.describe(null, null));
        assertEquals("self=none gw=none",
                LinkSummary.describe(Collections.emptyList(), " "));
    }

    @Test
    public void moreThanOneAddressStaysOneToken() {
        String line = LinkSummary.describe(
                Arrays.asList("10.0.3.107/24", "10.0.0.2/8"), "10.0.3.1");
        assertEquals("self=10.0.3.107/24,10.0.0.2/8 gw=10.0.3.1", line);
        assertEquals(2, line.split(" ").length);
    }
}
