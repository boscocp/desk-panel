package dev.bosco.deskpanel;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * One battery broadcast, turned into the payload's {@code battery} object.
 *
 * <p>No Android imports, so {@code ./gradlew test} covers it on the JVM — the
 * rule in {@code android/CLAUDE.md}. The Android half of T5.4 is a receiver
 * that reads four extras out of an Intent and hands them here; everything that
 * could be wrong about the numbers is in this file, where a test can reach it.
 *
 * <p>The shape is the one {@code web/js/mock.js} already feeds the panel:
 *
 * <pre>{level: 87, tempC: 31.5, charging: true}</pre>
 */
public final class BatteryReading {

    /**
     * {@code EXTRA_TEMPERATURE} is in tenths of a degree Celsius: 315 means
     * 31.5. Naming it is worth a constant, because the units are the one thing
     * about this API that silently produces a plausible wrong answer — a panel
     * claiming 315 degrees is obvious, one claiming 31 when it is 31.5 is not.
     */
    private static final double TENTHS_PER_DEGREE = 10.0;

    /**
     * What the receiver passes for an extra the broadcast did not carry, and
     * the default it hands {@code getIntExtra}.
     *
     * <p>Not -1, which is the obvious choice and is wrong for the temperature:
     * -1 tenths is -0.1 degrees, a real if unlikely reading, so a missing extra
     * would arrive indistinguishable from a cold morning. A value no sensor can
     * produce keeps "absent" and "low" separable, which is the whole reason
     * this constant is shared rather than written at each call site.
     */
    public static final int ABSENT = Integer.MIN_VALUE;

    private BatteryReading() {
    }

    /**
     * The four extras of {@code ACTION_BATTERY_CHANGED}, as the object the page
     * expects.
     *
     * @param level    {@code EXTRA_LEVEL}, on the scale below, or {@link #ABSENT}
     * @param scale    {@code EXTRA_SCALE}, the value {@code level} is out of.
     *                 Almost always 100, and deliberately not assumed to be:
     *                 the extra exists precisely because it is not guaranteed,
     *                 and a device reporting out of 255 would otherwise render a
     *                 full battery as 34%.
     * @param tenthsC  {@code EXTRA_TEMPERATURE}, in tenths of a degree, or
     *                 {@link #ABSENT}. The level decides whether there is a
     *                 reading at all; a missing temperature only costs the
     *                 {@code tempC} key.
     * @param charging whether {@code EXTRA_STATUS} says charging or full
     * @return a JSON object literal, or null if the broadcast carried no usable
     *         level. Null means "say nothing", never "say zero": a panel
     *         reporting 0% on a phone at 87% would be read as a flat battery,
     *         and this is a diagnostic whose only job is to be trusted.
     */
    public static String json(int level, int scale, int tenthsC, boolean charging) {
        if (level < 0 || scale <= 0) {
            return null;
        }

        try {
            JSONObject battery = new JSONObject();
            battery.put("level", percent(level, scale));
            if (plausible(tenthsC)) {
                // Left out rather than sent as a number when the extra was
                // missing. getIntExtra's default lands here as a reading, and
                // -0.1 degrees is exactly the kind of wrong that looks right
                // enough to render; the page's formatTemp already draws an
                // absent value as "--".
                battery.put("tempC", celsius(tenthsC));
            }
            battery.put("charging", charging);
            return battery.toString();
        } catch (JSONException impossible) {
            // Only thrown for a null key or a non-finite double, and celsius()
            // below rules out the second. Treated as "no reading" rather than
            // propagated: the battery line is a decoration on a panel whose
            // real content must not fail with it.
            return null;
        }
    }

    /**
     * Level as a whole percent, clamped to 0..100.
     *
     * <p>Clamped rather than trusted: this number is rendered straight onto the
     * panel, and a device that reports a level above its own scale — which
     * happens, briefly, on some chargers — would otherwise put "104%" on screen
     * and make every other number on it look unreliable too.
     */
    static int percent(int level, int scale) {
        // Rounded, not truncated: at scale 100 the two agree, and at any other
        // scale truncation loses up to a whole percent for no reason.
        long pct = Math.round((level * 100.0) / scale);
        return (int) Math.max(0, Math.min(100, pct));
    }

    /**
     * Tenths of a degree as degrees, keeping the one decimal the extra carries.
     * Rounding to a whole degree would hide the drift this task exists to
     * watch, and adding digits would invent precision the sensor has not got.
     */
    static double celsius(int tenthsC) {
        return tenthsC / TENTHS_PER_DEGREE;
    }

    /**
     * Whether a temperature could have come from a battery rather than from a
     * missing extra. Wide on purpose — the job is to reject -1 tenths and a
     * zeroed struct, not to second-guess a phone in a hot car.
     */
    private static boolean plausible(int tenthsC) {
        return tenthsC > -500 && tenthsC < 1500;
    }
}
