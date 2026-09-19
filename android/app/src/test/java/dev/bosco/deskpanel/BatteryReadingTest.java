package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

/**
 * The battery broadcast's four extras, turned into the payload's object, on the
 * JVM (T5.4). The Android half is a receiver that reads an Intent; everything
 * that can be wrong about the numbers is here.
 */
public class BatteryReadingTest {

    @Test
    public void producesTheShapeMockJsAlreadyFeedsThePage() throws Exception {
        JSONObject battery = new JSONObject(BatteryReading.json(87, 100, 315, true));

        assertEquals(87, battery.getInt("level"));
        assertEquals(31.5, battery.getDouble("tempC"), 0.001);
        assertTrue(battery.getBoolean("charging"));
    }

    @Test
    public void temperatureIsTenthsOfADegree() {
        // The trap this task names: 315 is 31.5 degrees, and a panel that
        // dropped the tenth would hide exactly the drift it is watching for.
        assertEquals(31.5, BatteryReading.celsius(315), 0.001);
        assertEquals(40.1, BatteryReading.celsius(401), 0.001);
        assertEquals(0.0, BatteryReading.celsius(0), 0.001);
    }

    @Test
    public void levelIsReadAgainstItsOwnScale() {
        // The extra exists because 100 is not guaranteed. Against a scale of
        // 255 a full battery read as a literal level would render as 34%.
        assertEquals(100, BatteryReading.percent(255, 255));
        assertEquals(50, BatteryReading.percent(128, 255));
        assertEquals(87, BatteryReading.percent(87, 100));
    }

    @Test
    public void levelIsClampedRatherThanTrusted() {
        assertEquals(100, BatteryReading.percent(104, 100));
        assertEquals(0, BatteryReading.percent(0, 100));
    }

    @Test
    public void noUsableLevelMeansNoReadingRatherThanZero() {
        // Zero is the dangerous default here: a panel reporting 0% on a phone
        // at 87% reads as a flat battery, and this number's only job is to be
        // trusted.
        assertNull(BatteryReading.json(BatteryReading.ABSENT, 100, 315, true));
        assertNull(BatteryReading.json(87, 0, 315, true));
        assertNull(BatteryReading.json(87, BatteryReading.ABSENT, 315, true));
    }

    @Test
    public void aMissingTemperatureCostsTheKeyAndNotTheReading() throws Exception {
        JSONObject battery =
                new JSONObject(BatteryReading.json(87, 100, BatteryReading.ABSENT, false));

        assertEquals(87, battery.getInt("level"));
        assertFalse("an absent temperature must not arrive as a number",
                battery.has("tempC"));
        assertFalse(battery.getBoolean("charging"));
    }

    @Test
    public void aBelowZeroReadingIsATemperatureAndNotAnAbsence() throws Exception {
        // -1 tenths is -0.1 degrees, which is why ABSENT cannot be -1: the two
        // would be indistinguishable on a cold morning.
        JSONObject battery = new JSONObject(BatteryReading.json(87, 100, -1, false));

        assertEquals(-0.1, battery.getDouble("tempC"), 0.001);
    }
}
