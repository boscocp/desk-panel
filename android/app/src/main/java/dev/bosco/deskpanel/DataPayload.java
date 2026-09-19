package dev.bosco.deskpanel;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * Merges the server's two responses into the one payload the page expects.
 *
 * <p>No Android imports, so {@code ./gradlew test} covers it on the JVM
 * without a device — the rule in {@code android/CLAUDE.md}, and this is the
 * part of T5.1 worth testing. {@code org.json} is bundled with Android rather
 * than added to the APK; the JVM stub it ships with throws, so
 * {@code build.gradle.kts} puts the real artefact on the <em>test</em>
 * classpath only.
 *
 * <p>The payload shape is a contract between three places: {@code web/js/mock.js},
 * the server's {@code /quotes} and {@code /weather} responses, and this class.
 * Changing a key means changing all three (see {@code tasks/T1.2-mock-fixtures.md}).
 *
 * <pre>
 * {quotes: [{symbol, price, changePct}],
 *  fx:     [{pair, rate, changePct}],
 *  crypto: [{symbol, price, changePct}],
 *  weather: {tempC, minC, maxC, code, city},
 *  stale:  bool}
 * </pre>
 *
 * <p>{@code battery} and {@code night} are absent on purpose: T5.4 and T6.4 own
 * them, and a key invented here would have to be un-invented there.
 */
public final class DataPayload {

    private DataPayload() {
    }

    /**
     * Both responses into one object literal, or null if either is unusable.
     *
     * <p><b>All or nothing, and that is a deliberate choice about wiping.</b>
     * {@code window.onData} is a full replacement, not a patch: {@code app.js}
     * clears each section before rendering it, so a payload missing {@code
     * weather} blanks the weather card rather than leaving it alone. Sending
     * half a payload would therefore erase the half that failed — which is
     * worse than sending nothing, because the panel already holds values that
     * are merely a minute old. Skipping the cycle keeps them, and the {@code
     * data=err} marker says the cycle was skipped.
     *
     * @param quotesJson  the body of {@code GET /quotes}, or null if it failed
     * @param weatherJson the body of {@code GET /weather}, or null if it failed
     * @return a JSON object literal safe to interpolate into JavaScript, or null
     */
    public static String merge(String quotesJson, String weatherJson) {
        if (quotesJson == null || weatherJson == null) {
            return null;
        }

        try {
            JSONObject quotes = new JSONObject(quotesJson);
            JSONObject weather = new JSONObject(weatherJson);

            JSONObject payload = new JSONObject();
            payload.put("quotes", quotes.opt("quotes"));
            payload.put("fx", quotes.opt("fx"));
            payload.put("crypto", quotes.opt("crypto"));

            // The server's weather response carries its own `stale`, which
            // belongs to the payload rather than to the weather card. Removing
            // it keeps the page's weather object exactly the shape mock.js
            // feeds it.
            weather.remove("stale");
            payload.put("weather", weather);

            // Either upstream being stale makes the panel stale. The badge
            // means "something here is older than it looks", and that is true
            // if it is true of any part.
            payload.put("stale",
                    quotes.optBoolean("stale", false) || hasStale(weatherJson));

            return escapeForScript(payload.toString());
        } catch (JSONException malformed) {
            // A body that is not JSON is a failure like any other: keep what
            // the panel has. It reaches the log through the caller's marker.
            return null;
        }
    }

    /** Whether the raw weather body claimed staleness, read before it was stripped. */
    private static boolean hasStale(String weatherJson) {
        try {
            return new JSONObject(weatherJson).optBoolean("stale", false);
        } catch (JSONException malformed) {
            return false;
        }
    }

    /**
     * Makes a JSON string safe as a JavaScript <em>literal</em>.
     *
     * <p>JSON is very nearly a subset of JavaScript expression syntax, and the
     * exception is exactly two characters: U+2028 LINE SEPARATOR and U+2029
     * PARAGRAPH SEPARATOR are legal unescaped inside a JSON string and were
     * line terminators in JavaScript before ES2019 — so a ticker name or a
     * city containing one would end the statement mid-string and leave a
     * syntax error inside {@code evaluateJavascript}, which reports nothing.
     *
     * <p>The WebView on this device is new enough not to care. It is escaped
     * anyway because the cost is two replacements on a few hundred bytes once
     * a minute, and the failure it prevents is silent.
     *
     * <p>Ordinary quotes need no help here: they never survive {@code
     * JSONObject.toString()} unescaped, which is the whole reason this class
     * builds the payload through {@code org.json} rather than by concatenating
     * strings (T5.1 step 5).
     */
    static String escapeForScript(String json) {
        return json.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029");
    }
}
