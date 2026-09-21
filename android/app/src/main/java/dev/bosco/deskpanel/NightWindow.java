package dev.bosco.deskpanel;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.Calendar;

/**
 * The night profile's window, and the one question it answers: is the panel
 * inside it right now (T6.4)?
 *
 * <p>No Android imports, so {@code ./gradlew test} covers it on the JVM
 * without a device — the rule in {@code android/CLAUDE.md}, and the acceptance
 * greps for it. {@code org.json} is bundled with Android rather than added to
 * the APK, exactly as it is for {@link DataPayload}.
 *
 * <p><b>This is the second implementation of a predicate the page already
 * has</b>, and the duplication is deliberate rather than an oversight.
 * {@code isNight} in {@code web/js/format.js} decides what the panel looks
 * like; this decides what the backlight does, and the two are applied by
 * mechanisms that do not meet: one is a CSS custom property, the other is
 * {@code WindowManager.LayoutParams.screenBrightness}, which no page can
 * reach. Pushing a boolean from here into the page would make the browser —
 * where there is no Java at all and {@code js/mock.js} is the whole feed —
 * the one environment where the night profile could not be developed. Both
 * copies read the same two bounds out of the same payload and compare them
 * against the same device clock, so they can disagree only for the seconds
 * between a minute boundary and the next refresh.
 *
 * <p><b>The phone's clock decides, not the PC's.</b> The window is configured
 * on the PC and evaluated here, because the panel is the thing whose screen
 * dims and the phone is the thing sitting on the desk. The opposite reading —
 * the server sending {@code night: true} — is just as plausible and produces a
 * panel that dims an hour late for ever after a timezone change, with nothing
 * in the log to explain it.
 */
public final class NightWindow {

    /** Minutes since local midnight, 0..1439. */
    private final int startMinute;
    private final int endMinute;

    private NightWindow(int startMinute, int endMinute) {
        this.startMinute = startMinute;
        this.endMinute = endMinute;
    }

    /**
     * The window carried by a payload, or null if there is not a usable one.
     *
     * <p>Null for every kind of malformed input — no {@code night} object, a
     * bound that is not a time, or two bounds that are the same instant — and
     * the caller treats null as "day". That is the right way round: a typo in
     * a file on the PC costs the dimming and never the panel, which is the
     * same rule the theme name follows (T6.7). {@code isNight} in
     * {@code web/js/format.js} returns false for all three for the same
     * reason.
     *
     * @param payloadJson a merged payload from {@link DataPayload}, or null
     * @return the window, or null if the payload does not carry a usable one
     */
    public static NightWindow parse(String payloadJson) {
        if (payloadJson == null) {
            return null;
        }
        try {
            JSONObject night = new JSONObject(payloadJson).optJSONObject("night");
            if (night == null) {
                return null;
            }
            Integer start = minuteOfDay(night.opt("start"));
            Integer end = minuteOfDay(night.opt("end"));
            if (start == null || end == null || start.equals(end)) {
                return null;
            }
            return new NightWindow(start, end);
        } catch (JSONException malformed) {
            return null;
        }
    }

    /**
     * Whether {@code minuteOfDay} falls inside the window.
     *
     * <p>Half-open, and it has to be: the start is night and the end is not,
     * so a window ending at 07:00 leaves the panel bright at 07:00 exactly
     * rather than for one more minute. The wrap across midnight is the case
     * that is wrong first and is what {@code NightWindowTest} spends most of
     * its assertions on — 22:00 to 07:00 is the shipped default, so the
     * ordinary path through this method is the wrapping one.
     */
    public boolean covers(int minuteOfDay) {
        if (startMinute < endMinute) {
            return minuteOfDay >= startMinute && minuteOfDay < endMinute;
        }
        return minuteOfDay >= startMinute || minuteOfDay < endMinute;
    }

    /**
     * Minutes since local midnight, from a calendar the caller owns.
     *
     * <p>A parameter rather than {@code Calendar.getInstance()} inside this
     * class, which is the whole reason the wrap can be tested at all: a
     * predicate that reads the clock itself is a predicate whose midnight
     * case can only be exercised at midnight.
     */
    public static int minuteOfDay(Calendar now) {
        return now.get(Calendar.HOUR_OF_DAY) * 60 + now.get(Calendar.MINUTE);
    }

    /**
     * One bound as minutes since midnight, or null if it is not a time.
     *
     * <p>Accepts {@code "HH:MM"}, which is what {@code server/config.toml}
     * ships and what the payload carries, and a bare hour as a number, which
     * {@code web/js/format.js} accepts too. The parity is the point: two
     * readers of one contract that disagreed about what a bound may look like
     * would dim the glow and not the backlight, or the other way round.
     *
     * <p>Minutes are honoured rather than rounded down to the hour. "22:30"
     * that dimmed at 22:00 would be half an hour of a panel doing something
     * nobody asked it to, every night.
     */
    static Integer minuteOfDay(Object bound) {
        if (bound instanceof Number) {
            int hour = ((Number) bound).intValue();
            // A bare hour only. Minutes-since-midnight as a number would make
            // 22 mean 00:22 on one reader and 22:00 on the other, which is the
            // kind of agreement that is easier to refuse than to document.
            return hour >= 0 && hour <= 23 ? hour * 60 : null;
        }
        if (!(bound instanceof String)) {
            return null;
        }
        String text = ((String) bound).trim();
        int colon = text.indexOf(':');
        if (colon < 1 || colon != text.lastIndexOf(':')) {
            return null;
        }
        Integer hours = digits(text.substring(0, colon), 2);
        Integer minutes = digits(text.substring(colon + 1), 2);
        if (hours == null || minutes == null
                || hours > 23 || minutes > 59
                // "7:5" is not a time, and Integer.parseInt would happily read
                // it as 07:05. The minute field is two digits or it is nothing.
                || text.length() - colon - 1 != 2) {
            return null;
        }
        return hours * 60 + minutes;
    }

    /**
     * {@code text} as a number, or null unless it is one to {@code maxDigits}
     * ASCII digits.
     *
     * <p>Hand-rolled rather than {@code Integer.parseInt}, because that
     * accepts a leading sign and a great deal of Unicode: {@code parseInt}
     * reads "+2" as 2 and Arabic-Indic digits as their values, so "+2:00" and
     * a string of decorative digits would both become legal bounds. A config
     * file is not hostile input, but a bound that parsed by accident would dim
     * the panel at a time nobody wrote down.
     */
    private static Integer digits(String text, int maxDigits) {
        if (text.isEmpty() || text.length() > maxDigits) {
            return null;
        }
        int value = 0;
        for (int i = 0; i < text.length(); i += 1) {
            char c = text.charAt(i);
            if (c < '0' || c > '9') {
                return null;
            }
            value = value * 10 + (c - '0');
        }
        return value;
    }
}
