package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** T9.4, ADR 0018: where data and presses go, open or private. */
public class PanelLinkTest {

    private static final String KEY = "test-key-".repeat(5);

    @Test
    public void noKeyIsTheOldPlainHttp() {
        PanelLink open = new PanelLink("");
        assertFalse(open.isPrivate());
        assertNull(open.key());
        assertEquals("http://192.168.1.100:8777", open.base("192.168.1.100"));
        assertFalse(new PanelLink(null).isPrivate());
    }

    @Test
    public void aKeyMovesDataToTheTlsPortAndIsSent() {
        PanelLink link = new PanelLink(KEY);
        assertTrue(link.isPrivate());
        assertEquals(KEY, link.key());
        assertEquals("https://192.168.1.100:8778", link.base("192.168.1.100"));
    }

    @Test
    public void thePortsAreTheServers() {
        // server/private.py TLS_PORT and server.py PORT; a drift here is a
        // panel that dials a port nothing listens on.
        assertEquals(8777, PanelLink.PLAIN_PORT);
        assertEquals(8778, PanelLink.TLS_PORT);
        assertEquals("X-Panel-Key", PanelLink.KEY_HEADER);
    }
}
