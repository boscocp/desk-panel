package dev.bosco.deskpanel;

/**
 * One line of {@code GET /spectrum}, checked before it goes anywhere near the
 * page (T8.5, ADR 0021).
 *
 * <p>A frame is sixteen bars, two lowercase hex digits each: 32 characters
 * from {@code [0-9a-f]} and nothing else. That is what {@code server/spectrum.py}
 * writes, and it is also exactly what makes the string safe to put between
 * quotes in {@code evaluateJavascript} -- the argument {@code DataPayload}
 * makes for the payload, made here by a whitelist. Anything else is dropped.
 *
 * <p>No Android imports, so {@code ./gradlew test} covers it on the JVM.
 */
public final class SpectrumFrame {

    /** Bars per frame. Matches {@code BARS} in server/spectrum.py. */
    public static final int BARS = 16;

    private SpectrumFrame() {
    }

    /**
     * {@code line} if it is a well-formed frame, else null. A trailing
     * {@code \r} is forgiven; nothing else is.
     */
    public static String parse(String line) {
        if (line == null) {
            return null;
        }
        String frame = line.endsWith("\r") ? line.substring(0, line.length() - 1) : line;
        if (frame.length() != BARS * 2) {
            return null;
        }
        for (int i = 0; i < frame.length(); i++) {
            char c = frame.charAt(i);
            boolean hex = (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
            if (!hex) {
                return null;
            }
        }
        return frame;
    }
}
