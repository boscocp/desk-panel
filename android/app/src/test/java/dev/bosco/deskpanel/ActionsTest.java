package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotSame;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

/**
 * The page's half of ADR 0015's promise, asserted (T8.2).
 *
 * <p>The tests that matter are not "a known id works". They are that an id the
 * page invented reaches no URL, and that the URL is built from this app's own
 * constant rather than from the argument — because the whole reason this class
 * exists instead of a {@code contains} at the call site is that a
 * {@code @JavascriptInterface} is reachable by every script in the WebView.
 */
public class ActionsTest {

    @Test
    public void resolveReturnsThisAppsConstantAndNotTheCallersString() {
        // Not assertEquals: a String with the same characters would pass that
        // and would mean the caller's bytes are what ends up in the URL.
        String fromThePage = new StringBuilder("mute-").append("audio").toString();
        assertNotSame(fromThePage, Actions.resolve(fromThePage));
        assertSame(Actions.ALLOWED.get(0), Actions.resolve(fromThePage));
    }

    @Test
    public void anIdThatIsNotAllowedResolvesToNothing() {
        assertNull(Actions.resolve("shutdown"));
        assertNull(Actions.resolve("mute-everything"));
        assertNull(Actions.resolve(""));
        assertNull(Actions.resolve(null));
    }

    @Test
    public void nothingShapedLikeAPathOrACommandSurvives() {
        // None of these can reach a URL even if the server's own guard were
        // one day written carelessly. Two allowlists, and this is the near one.
        String[] hostile = {
            "../ping",
            "mute-audio/../../etc",
            "mute-audio?x=1",
            "mute-audio mute-mic",
            "mute-audio;rm -rf /",
            "MUTE-AUDIO",
            " mute-audio",
            "mute-audio ",
            "mute-audio\n",
            "http://elsewhere/action/mute-audio",
        };
        for (String candidate : hostile) {
            assertNull(candidate, Actions.resolve(candidate));
            assertNull(candidate, Actions.urlFor("192.168.1.100", 8777, candidate));
        }
    }

    @Test
    public void urlForBuildsTheRouteTheServerReserved() {
        assertEquals(
                "http://192.168.1.100:8777/action/mute-mic",
                Actions.urlFor("192.168.1.100", 8777, "mute-mic"));
    }

    @Test
    public void noHostIsNoUrl() {
        // A poller built before the PC's address was known must not produce
        // "http://:8777/action/..." and send it somewhere.
        assertNull(Actions.urlFor(null, 8777, "mute-mic"));
        assertNull(Actions.urlFor("", 8777, "mute-mic"));
    }

    @Test
    public void theAllowlistCannotBeEditedByAnyoneHoldingIt() {
        try {
            Actions.ALLOWED.add("shutdown");
            throw new AssertionError("ALLOWED is mutable");
        } catch (UnsupportedOperationException expected) {
            assertTrue(Actions.ALLOWED.size() == 2);
        }
    }

    @Test
    public void theTwoIdsAreTheOnesTheServerKnows() {
        // server/actions.py's CATALOGUE, spelled the same. The duplication is
        // deliberate (see Actions' javadoc) and this is the line that fails
        // when only one side is renamed.
        assertEquals("mute-audio", Actions.ALLOWED.get(0));
        assertEquals("mute-mic", Actions.ALLOWED.get(1));
        assertEquals(2, Actions.ALLOWED.size());
    }

    @Test
    public void theAllowlistCarriesEveryIdTheServerKnows() {
        // T10.1. The same list is written in three languages -- this one,
        // `actions.CATALOGUE` in Python, and `words.actions` in format.js --
        // and until now nothing compared them. A half-added action draws no
        // button, or draws one this bridge refuses; both fail safe, and both
        // look like the panel working.
        //
        // **The duplication itself stays.** ADR 0015 wants the phone's
        // allowlist independent of the server's, so a compromised asset
        // cannot widen what the bridge will send. What was missing was only a
        // check that they agree, and this is it -- read from the description
        // `server/tests/test_payload_contract.py` generates.
        List<String> known = Contract.actionIds();
        assertEquals("the server's catalogue and this app's allowlist have drifted; "
                + "see ADR 0015 and tasks/T10.1", known, Actions.ALLOWED);
    }
}
