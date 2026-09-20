package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

/**
 * The payload merge, on the JVM. This is the part of T5.1 worth testing: the
 * poller around it is sockets and scheduling, and this is the piece that
 * decides what the panel is told.
 */
public class DataPayloadTest {

    private static final String QUOTES =
            "{\"quotes\":[{\"symbol\":\"PETR4\",\"price\":48.5,\"changePct\":-0.23}],"
            + "\"fx\":[{\"pair\":\"USD/BRL\",\"rate\":5.1434,\"changePct\":0.36882}],"
            + "\"crypto\":[{\"symbol\":\"BTC\",\"price\":81470.0,\"changePct\":1.016}],"
            + "\"stale\":false}";

    private static final String WEATHER =
            "{\"tempC\":24.0,\"minC\":15.5,\"maxC\":26.1,\"code\":2,"
            + "\"city\":\"São Paulo\",\"stale\":false}";

    @Test
    public void mergeProducesTheContractShape() throws Exception {
        JSONObject payload = new JSONObject(DataPayload.merge(QUOTES, WEATHER));

        assertEquals(1, payload.getJSONArray("quotes").length());
        assertEquals(1, payload.getJSONArray("fx").length());
        assertEquals(1, payload.getJSONArray("crypto").length());
        assertEquals("PETR4",
                payload.getJSONArray("quotes").getJSONObject(0).getString("symbol"));
        assertFalse(payload.getBoolean("stale"));
    }

    @Test
    public void weatherKeepsItsOwnShapeAndLosesOnlyTheStaleFlag() throws Exception {
        JSONObject weather = new JSONObject(DataPayload.merge(QUOTES, WEATHER))
                .getJSONObject("weather");

        // Exactly what mock.js feeds the page, so app.js needs no changes.
        assertEquals(24.0, weather.getDouble("tempC"), 0.001);
        assertEquals(15.5, weather.getDouble("minC"), 0.001);
        assertEquals(26.1, weather.getDouble("maxC"), 0.001);
        assertEquals(2, weather.getInt("code"));
        assertEquals("São Paulo", weather.getString("city"));
        assertFalse("stale belongs to the payload, not the weather card",
                weather.has("stale"));
    }

    @Test
    public void theThemeRidesQuotesThroughUntouched() throws Exception {
        // T6.7: the name of a directory in the APK's assets, chosen by the PC's
        // config. This class passes it through and never interprets it -- the
        // page owns the fallback, because the page is the only layer that knows
        // which themes the APK was built with.
        String themed = QUOTES.replace("\"stale\":false", "\"stale\":false,\"theme\":\"plain\"");
        assertEquals("plain",
                new JSONObject(DataPayload.merge(themed, WEATHER)).getString("theme"));

        // A name no theme answers to is still passed through: rejecting it here
        // would turn a cosmetic typo into a decision made by the wrong layer.
        String nonsense = QUOTES.replace("\"stale\":false", "\"stale\":false,\"theme\":\"nope\"");
        assertEquals("nope",
                new JSONObject(DataPayload.merge(nonsense, WEATHER)).getString("theme"));
    }

    @Test
    public void anAbsentOrEmptyThemeLeavesTheKeyOutAltogether() throws Exception {
        // An older server on the PC sends no theme at all, and a config with an
        // empty one means the same thing. Both have to reach the page as
        // `undefined` rather than as "", because host.js reads a falsy name as
        // "use the fallback" and an empty string that survived would be a name
        // no theme answers to -- the same outcome, reached by a warning nobody
        // needed to read.
        assertFalse("no theme key in, no theme key out",
                new JSONObject(DataPayload.merge(QUOTES, WEATHER)).has("theme"));

        String empty = QUOTES.replace("\"stale\":false", "\"stale\":false,\"theme\":\"\"");
        assertFalse(new JSONObject(DataPayload.merge(empty, WEATHER)).has("theme"));
    }

    @Test
    public void eitherUpstreamBeingStaleMakesThePayloadStale() throws Exception {
        String staleQuotes = QUOTES.replace("\"stale\":false", "\"stale\":true");
        assertTrue(new JSONObject(DataPayload.merge(staleQuotes, WEATHER))
                .getBoolean("stale"));

        String staleWeather = WEATHER.replace("\"stale\":false", "\"stale\":true");
        assertTrue(new JSONObject(DataPayload.merge(QUOTES, staleWeather))
                .getBoolean("stale"));
    }

    @Test
    public void aMissingHalfSkipsTheCycleRatherThanWipingIt() {
        // onData is a full replacement and app.js clears each section before
        // rendering it, so half a payload erases the half that failed. The
        // panel already holds values a minute old; keeping them is better.
        assertNull(DataPayload.merge(null, WEATHER));
        assertNull(DataPayload.merge(QUOTES, null));
        assertNull(DataPayload.merge(null, null));
    }

    @Test
    public void aSectionMissingFromTheServerSkipsTheCycleRatherThanBlankingIt() {
        // JSONObject.put removes the mapping when handed null, so an absent
        // array used to produce a payload without that key -- app.js falls
        // back to `|| []` and blanks the section, while the cycle still logs
        // data=ok. Silent, and the opposite of what merge promises.
        String noFx = QUOTES.replace("\"fx\":[{\"pair\":\"USD/BRL\",\"rate\":5.1434,"
                + "\"changePct\":0.36882}],", "");
        assertNull(DataPayload.merge(noFx, WEATHER));
    }

    @Test
    public void anEmptySectionIsNotTheSameAsAMissingOne() {
        // A config with no crypto configured is legitimate and must still
        // render; only an absent key is a failure.
        String emptyCrypto = QUOTES.replace(
                "\"crypto\":[{\"symbol\":\"BTC\",\"price\":81470.0,\"changePct\":1.016}]",
                "\"crypto\":[]");
        assertNotNull(DataPayload.merge(emptyCrypto, WEATHER));
    }

    @Test
    public void malformedJsonIsAFailureNotAnException() {
        assertNull(DataPayload.merge("not json at all", WEATHER));
        assertNull(DataPayload.merge(QUOTES, "{unclosed"));
        assertNull(DataPayload.merge("", WEATHER));
    }

    @Test
    public void aQuoteInASymbolCannotBreakOutOfTheCall() throws Exception {
        // T5.1 step 5. The hostile string is a symbol that closes its own
        // literal and appends a call; building the payload by concatenation
        // would hand evaluateJavascript a second statement.
        String hostile = "{\"quotes\":[{\"symbol\":\"X\\\");alert(1);//\","
                + "\"price\":1.0,\"changePct\":0.0}],\"fx\":[],\"crypto\":[],"
                + "\"stale\":false}";

        String merged = DataPayload.merge(hostile, WEATHER);

        // It survives as data, and it is still one expression: parsing it back
        // gives the symbol verbatim rather than a truncated string.
        assertEquals("X\");alert(1);//",
                new JSONObject(merged).getJSONArray("quotes").getJSONObject(0)
                        .getString("symbol"));
        assertFalse("the closing quote was not escaped", merged.contains("\"X\");"));
    }

    @Test
    public void lineSeparatorsAreEscapedSoTheLiteralStaysOneStatement() {
        // U+2028 and U+2029 are legal unescaped inside a JSON string and were
        // JavaScript line terminators before ES2019, so they would end the
        // statement mid-string with no error anyone can see.
        String withSeparator = QUOTES.replace("PETR4", "PET\u2028R4");
        String merged = DataPayload.merge(withSeparator, WEATHER);

        assertFalse(merged.contains("\u2028"));
        assertTrue(merged.contains("\\u2028"));
    }

    @Test
    public void escapeForScriptLeavesOrdinaryTextAlone() {
        assertEquals("{\"a\":\"b\"}", DataPayload.escapeForScript("{\"a\":\"b\"}"));
    }

    // --- withBattery (T5.4) -------------------------------------------------

    private static final String BATTERY = "{\"level\":87,\"tempC\":31.5,\"charging\":true}";

    @Test
    public void batteryIsFoldedInWithoutDisturbingTheRest() throws Exception {
        String merged = DataPayload.merge(QUOTES, WEATHER);
        JSONObject payload = new JSONObject(DataPayload.withBattery(merged, BATTERY));

        assertEquals(87, payload.getJSONObject("battery").getInt("level"));
        assertEquals(31.5, payload.getJSONObject("battery").getDouble("tempC"), 0.001);
        // Everything merge produced is still there and still itself.
        assertEquals(1, payload.getJSONArray("quotes").length());
        assertEquals("São Paulo", payload.getJSONObject("weather").getString("city"));
        assertFalse(payload.getBoolean("stale"));
    }

    @Test
    public void noBroadcastYetLeavesThePayloadExactlyAsItWas() {
        String merged = DataPayload.merge(QUOTES, WEATHER);
        assertEquals(merged, DataPayload.withBattery(merged, null));
    }

    @Test
    public void aBadBatteryCostsTheBatteryAndNotThePanel() {
        // The opposite of merge's all-or-nothing rule, deliberately: this is a
        // diagnostic in the corner, and blanking B3, FX, CRYPTO and WEATHER
        // because a temperature would not parse is not a trade worth making.
        String merged = DataPayload.merge(QUOTES, WEATHER);

        assertEquals(merged, DataPayload.withBattery(merged, "not json"));
        assertEquals(merged, DataPayload.withBattery(merged, "[1,2,3]"));
    }

    @Test
    public void aFailedCycleStaysFailedWhateverTheBatterySays() {
        // withBattery must not conjure a payload out of a battery reading: a
        // cycle that produced nothing still has nothing to render.
        assertNull(DataPayload.withBattery(null, BATTERY));
    }

    @Test
    public void theFoldedPayloadIsStillSafeToInterpolate() {
        String merged = DataPayload.merge(QUOTES.replace("PETR4", "PET R4"), WEATHER);
        String folded = DataPayload.withBattery(merged, BATTERY);

        // Re-parsing and re-serialising must not undo the escape merge applied.
        assertFalse(folded.contains(" "));
        assertTrue(folded.contains("\\u2028"));
    }
}
