package dev.bosco.deskpanel;

/**
 * How the panel reaches a PC for data and presses: which scheme, which port,
 * and which key (T9.4, ADR 0018).
 *
 * <p>Two shapes, chosen at build time by whether {@code PANEL_KEY} is set in
 * {@code .env}:
 * <ul>
 *   <li><b>Open</b>, no key: {@code http://host:8777}, as the panel always
 *       was. Anyone on the Wi-Fi can read what it reads.</li>
 *   <li><b>Private</b>, with a key: {@code https://host:8778}, the PC's
 *       certificate pinned in {@code network_security_config.xml}, and the key
 *       in {@link #KEY_HEADER} on every request.</li>
 * </ul>
 *
 * <p>{@code /ping} is not here. It stays plain http on the plain port in both
 * shapes, because it is the login signal and a certificate problem must never
 * read as a logout; {@link PcPoller} builds its own URL.
 *
 * <p>Plain Java, no Android imports, so the URLs are covered on the JVM.
 */
public final class PanelLink {

    /** The PC server's plain port: {@code /ping}, and data when open. */
    public static final int PLAIN_PORT = 8777;

    /** The PC server's TLS port, {@code tls_port} in its config. */
    public static final int TLS_PORT = 8778;

    /** The header the server reads the key from. */
    public static final String KEY_HEADER = "X-Panel-Key";

    private final String key;

    /** @param key {@code BuildConfig.PANEL_KEY}; empty or null for open traffic */
    public PanelLink(String key) {
        this.key = key == null ? "" : key;
    }

    /** Whether data and presses go over TLS with the key. */
    public boolean isPrivate() {
        return !key.isEmpty();
    }

    /** The key to send, or null when there is none to send. */
    public String key() {
        return isPrivate() ? key : null;
    }

    /** {@code scheme://host:port}, no trailing slash. */
    public String base(String host) {
        return isPrivate()
                ? "https://" + host + ":" + TLS_PORT
                : "http://" + host + ":" + PLAIN_PORT;
    }
}
