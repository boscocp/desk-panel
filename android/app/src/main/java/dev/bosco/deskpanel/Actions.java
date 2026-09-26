package dev.bosco.deskpanel;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * What the panel is allowed to ask the PC to do, and nothing else (T8.2).
 *
 * <p>This is <b>the second allowlist</b>, and the duplication is deliberate.
 * The server has its own in {@code server/actions.py}, and
 * {@code docs/adr/0015-the-panel-can-act-on-the-pc.md} says why that one has to
 * exist: the request carries an id and nothing else, and the id is a key in a
 * lookup rather than a value that reaches a command. That argument is made
 * about a request arriving over the LAN.
 *
 * <p>This class makes it again on the other side of the wire, about an id
 * arriving from JavaScript. {@code MainActivity} exposes
 * {@code window.__actions.invoke(id)} to every script in the WebView, and an id
 * that went from there straight into a URL would be the same mistake a layer
 * earlier — the page would be choosing what the phone asks the PC for. So an id
 * from the page is matched against {@link #ALLOWED} and the URL is built from
 * the constant that matched, never from the argument.
 *
 * <p>Keeping the two lists in step is a real cost and it is the cheaper half of
 * the trade: a panel that drew a button the server refuses is a button that
 * does nothing, and a bridge that forwarded anything the page said would make
 * the server's allowlist the only thing between a compromised asset and the
 * desktop. The payload's {@code actions} key is what actually decides which
 * buttons are drawn — this is the floor under it, not the source of it.
 *
 * <p>No Android imports, so {@code ./gradlew test} covers it on the JVM
 * ({@code android/CLAUDE.md}).
 */
public final class Actions {

    /**
     * Every id this app will send, in the spelling the server knows.
     *
     * <p>Adding one here is not enough to make a button appear and is not meant
     * to be: the server has to enable it in {@code config.toml} and send it in
     * the payload. This list only says what the app is willing to relay.
     */
    public static final List<String> ALLOWED =
            Collections.unmodifiableList(Arrays.asList("mute-audio", "mute-mic"));

    private Actions() {
    }

    /**
     * The id from {@link #ALLOWED} equal to {@code candidate}, or null.
     *
     * <p>Returns the <b>constant</b> and not the argument, which is the whole
     * point of the method existing rather than a {@code contains} at the call
     * site. Every character that reaches the URL comes from this file; the
     * string the page handed over is compared and discarded.
     */
    public static String resolve(String candidate) {
        if (candidate == null) {
            return null;
        }
        for (String allowed : ALLOWED) {
            if (allowed.equals(candidate)) {
                return allowed;
            }
        }
        return null;
    }

    /**
     * {@code http://host:port/action/<id>}, or null if the id is not allowed.
     *
     * @param id an id straight off the JavaScript bridge, untrusted
     */
    public static String urlFor(String host, int port, String id) {
        String resolved = resolve(id);
        if (resolved == null || host == null || host.isEmpty()) {
            return null;
        }
        return "http://" + host + ":" + port + "/action/" + resolved;
    }
}
