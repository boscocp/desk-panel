package dev.bosco.deskpanel;

import java.util.List;

/**
 * Where the phone itself is on the network, for a {@code ping=err} line (T4.13).
 *
 * <p>On 2026-10-30 a power cut brought a mesh satellite back as a router of its
 * own: the phone took an address on the satellite's own subnet and could reach
 * neither PC, and for hours the log said only {@code SocketTimeoutException}
 * for both. A PC
 * that is off and a phone that is on the wrong network read the same from the
 * PC's side; they do not read the same from the phone's. So a failing cycle
 * also says which address and gateway the phone has, and the wrong subnet is
 * on the line instead of behind an adb session.
 *
 * <p>Plain Java, no Android imports: {@code PanelService} reads the link and
 * hands the strings here, so the format is covered on the JVM.
 */
public final class LinkSummary {

    private LinkSummary() {
    }

    /**
     * @param addresses the active network's addresses as {@code ip/prefix};
     *                  IPv6 ones are dropped, because the PCs are dialled over
     *                  IPv4 and a link-local {@code fe80::} only adds noise
     * @param gateway   the default route's gateway, or null when there is none
     * @return {@code self=<ip>/<prefix>[,...] gw=<ip>}, with {@code none} for
     *         either half that is missing. Two tokens, neither with a space in
     *         it, so the greps that match {@code ping=} lines as a prefix keep
     *         matching (T4.8).
     */
    public static String describe(List<String> addresses, String gateway) {
        StringBuilder self = new StringBuilder();
        if (addresses != null) {
            for (String address : addresses) {
                if (address == null || address.contains(":")) {
                    continue;
                }
                if (self.length() > 0) {
                    self.append(',');
                }
                self.append(address.trim());
            }
        }
        String gw = gateway == null || gateway.trim().isEmpty() ? "none" : gateway.trim();
        return "self=" + (self.length() > 0 ? self : "none") + " gw=" + gw;
    }
}
