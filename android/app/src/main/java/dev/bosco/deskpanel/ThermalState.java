package dev.bosco.deskpanel;

/**
 * The second authority over the screen: whether the device is too hot to keep
 * painting (T5.5, ADR 0012).
 *
 * <p>No Android imports, the same rule {@link PcState} follows and for the same
 * reason — the part worth testing is the hysteresis, and {@code ./gradlew test}
 * can drive it through a whole thermal cycle on the JVM in a millisecond, where
 * a device test would have to actually warm a phone up.
 *
 * <p>It decides <em>that</em> the verdict changed; it does not log it and it
 * does not touch a window. {@code MainActivity} owns both, and it is the single
 * place where this verdict and {@link PcState}'s are arbitrated.
 *
 * <h2>Why two thresholds</h2>
 *
 * <p>The screen is itself the heat source being managed, so a single threshold
 * oscillates by construction: blanking cools the device past the line, the
 * screen comes back, and it heats past the line again — a panel that flickers
 * on a timescale of minutes, which is worse than either state. Blanking at
 * {@value #BLANK_AT_C} and clearing at {@value #CLEAR_AT_C} puts seven degrees
 * between the two, so the device has genuinely cooled before the panel returns.
 *
 * <p>The numbers are constants rather than config. They are about what a
 * lithium cell tolerates, not about what the owner wants shown, and
 * {@code server/config.json} is documented as the place for display choices.
 */
public final class ThermalState {

    /**
     * Blank at or above this, in degrees Celsius.
     *
     * <p>Well under the 50-60 degrees where Android's own thermal throttling
     * acts: that is a hard net for the device, not a policy for the cell, and
     * by the time it fires the damage this class exists to avoid has been done
     * (ADR 0012).
     */
    public static final double BLANK_AT_C = 45.0;

    /**
     * Come back at or below this.
     *
     * <p>Two degrees under the 40 at which the panel's temperature reading
     * already turns amber, so the warning colour is still showing when the
     * screen returns. The order matters: the owner sees the panel come back
     * warm rather than come back looking fine and blank again.
     */
    public static final double CLEAR_AT_C = 38.0;

    private boolean tooHot;
    private boolean transitioned;

    /**
     * Feeds one temperature reading in.
     *
     * <p>Between the two thresholds the verdict is held, which is the whole
     * point: the answer depends on the direction of travel, not only on the
     * number. 41 degrees means "still blanking" on the way down and "still
     * painting" on the way up.
     *
     * @param tempC the battery temperature in degrees Celsius, from
     *              {@code ACTION_BATTERY_CHANGED}. A {@code NaN} is treated as
     *              no reading at all and holds the verdict — a sensor that
     *              stopped answering is not evidence that the device cooled
     * @param nowMs the time of the reading, on any monotonic scale the caller
     *              likes. Deliberately unused: the hysteresis above is a pure
     *              function of temperature and of the previous verdict, and
     *              nothing here needs a clock. It is in the signature because
     *              every state class in this project takes its time as a
     *              parameter rather than reading one ({@link PcState#record},
     *              {@link PcState#isDue}), and because a minimum dwell — the
     *              one plausible future rule here — would otherwise have to
     *              change this signature at every call site. Taking it now
     *              costs a parameter; adding it later costs an API change
     * @return true if this reading changed the verdict — i.e. exactly the
     *         readings on which a marker should be logged and the window
     *         retoggled
     */
    public boolean record(double tempC, long nowMs) {
        if (Double.isNaN(tempC)) {
            transitioned = false;
            return false;
        }

        boolean next = tooHot;
        if (tempC >= BLANK_AT_C) {
            next = true;
        } else if (tempC <= CLEAR_AT_C) {
            next = false;
        }

        transitioned = next != tooHot;
        tooHot = next;
        return transitioned;
    }

    /**
     * Whether the device is currently too hot to paint.
     *
     * <p>False before the first reading, which is the only safe default: the
     * panel has to be able to start up and show something on a device whose
     * battery broadcast has not arrived yet, and that broadcast is sticky, so
     * the wait is milliseconds rather than minutes.
     */
    public boolean isTooHot() {
        return tooHot;
    }

    /**
     * Whether the most recent {@link #record} changed the verdict. Sticky only
     * until the next reading, so callers that log on it log once per transition
     * and not once per broadcast — and this device broadcasts about every eight
     * seconds while charging.
     */
    public boolean transitioned() {
        return transitioned;
    }
}
