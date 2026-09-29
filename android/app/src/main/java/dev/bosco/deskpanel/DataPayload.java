package dev.bosco.deskpanel;

import org.json.JSONArray;
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
 *  stale:  bool,
 *  theme:  string,
 *  language: string,
 *  night:  {start, end},
 *  actions: [id, ...]}
 * </pre>
 *
 * <p>{@code battery} is added afterwards by {@link #withBattery}, because it
 * comes from the device rather than from the server and arrives on its own
 * schedule — a broadcast, never a poll (T5.4).
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

            // Every section has to be there, and this is checked rather than
            // assumed: JSONObject.put removes the mapping when handed null, so
            // a body missing one array would produce a payload missing that
            // key, app.js would fall back to `|| []`, and the section would be
            // blanked while the cycle still logged data=ok -- the exact silent
            // wipe the all-or-nothing rule above exists to prevent.
            JSONArray quoteRows = quotes.optJSONArray("quotes");
            JSONArray fxRows = quotes.optJSONArray("fx");
            JSONArray cryptoRows = quotes.optJSONArray("crypto");
            if (quoteRows == null || fxRows == null || cryptoRows == null) {
                return null;
            }

            JSONObject payload = new JSONObject();
            payload.put("quotes", quoteRows);
            payload.put("fx", fxRows);
            payload.put("crypto", cryptoRows);

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

            // Which theme the page should render with (T6.7). Passed straight
            // through and never interpreted: the set of themes lives in the
            // APK's assets, the page owns the fallback, and a name this class
            // did not recognise would be a name it had no business rejecting.
            //
            // Absent rather than empty when the server does not send it, so an
            // older server on the PC leaves window.onData's `theme` undefined
            // and the page falls back — the same path as a typo, already
            // specified. put(null) is how JSONObject removes a key, which is
            // exactly what is wanted here and is a trap everywhere else in
            // this file.
            String theme = quotes.optString("theme", "");
            payload.put("theme", theme.isEmpty() ? null : theme);

            // Which language the panel speaks (T6.11), passed straight through
            // for the same reason `theme` is: the set of packaged languages
            // lives in the APK, the page owns the fallback, and a tag this
            // class did not recognise would be a tag it had no business
            // rejecting.
            //
            // Absent rather than empty, so an older server leaves it
            // undefined and the page uses the panel's own language -- the
            // same path a typo takes.
            String language = quotes.optString("language", "");
            payload.put("language", language.isEmpty() ? null : language);

            // The night profile's window (T6.4), and like `theme` it is
            // passed straight through and never interpreted here. Two
            // readers take it from the payload and both are elsewhere:
            // {@link NightWindow} for the backlight and js/format.js for the
            // glow. Deciding it here would put the answer in a merge step
            // that runs once a minute, when what the window has to be
            // compared against is the clock at the moment it is asked.
            //
            // Absent rather than empty when the server does not send one, so
            // an older server on the PC leaves the page's `night` undefined
            // and both readers fall back to the day profile -- the same path
            // a typo in the bounds takes. put(null) is how JSONObject removes
            // a key, which is exactly what is wanted here.
            //
            // **This copy is the whole of the wiring, and it is true of every
            // line above it as well.** The payload is rebuilt key by key
            // rather than patched, so a key nobody names here simply does not
            // reach the phone: the page stays in its day profile for ever and
            // the backlight never dims, with a correct server, a correct page
            // and a correct predicate. That is how T6.4 shipped its first
            // build, and `e2e/check_night_marker.py` is what caught it.
            //
            // It is **no longer silent**, which this comment used to say it
            // was — and being read after the failure twice is what finally
            // bought a check (T10.1). `DataPayloadTest` asserts every
            // top-level key of `server/tests/fixtures/payload.json`, which the
            // server generates from its own assembly, so a key added on the PC
            // turns `./gradlew test` red here rather than vanishing. Adding a
            // line below and regenerating that file is the whole procedure.
            payload.put("night", quotes.optJSONObject("night"));

            // Which shortcut buttons the panel draws (T8.2), and it is the
            // fourth key to be passed straight through without being
            // interpreted -- the catalogue of what an id runs lives on the PC
            // (ADR 0015) and the words for it live in the APK, so this layer
            // has no opinion about either.
            //
            // **It is also the line the comment above turned out to be about.**
            // T8.2 was written end to end, tested in two themes in a real
            // browser, built, installed, and drew no buttons at all -- because
            // this file rebuilds the payload key by key and `actions` was not
            // among them. The server was sending it, the page was ready to draw
            // it, and the phone never saw the key. Exactly the failure the
            // night profile had, in the wave after the one that wrote that
            // warning down.
            //
            // An absent key is an empty list to the page rather than null: a
            // panel talking to an older server draws no buttons, which is the
            // same thing it does for a PC that enabled none.
            payload.put("actions", quotes.optJSONArray("actions"));

            // The owner's next meetings (T9.1, ADR 0017), passed straight
            // through like the four keys above. What an event is -- which one
            // is next, how long until it starts -- is decided in js/format.js
            // against the phone's clock, and what may be in it at all is
            // decided on the PC, before it is sent: no attendees, no body, and
            // no title when the owner turned titles off. This layer only
            // carries it, so it has nothing to filter and nothing to leak.
            //
            // Absent rather than empty for an older server, so the page leaves
            // the AGENDA card reserved -- the same thing it does for a PC with
            // no calendar connected.
            payload.put("agenda", quotes.optJSONObject("agenda"));

            return escapeForScript(payload.toString());
        } catch (JSONException malformed) {
            // A body that is not JSON is a failure like any other: keep what
            // the panel has. It reaches the log through the caller's marker.
            return null;
        }
    }

    /**
     * The {@code state} field of an action response, or {@code unknown}.
     *
     * <p>Here rather than in {@code DataPoller} for the reason every parser in
     * this project is here: {@code android/CLAUDE.md} says anything worth
     * testing lives in a plain class with no Android imports, and what a panel
     * does with a mixer's answer is worth testing — the value decides whether
     * a cross is drawn over a microphone icon, and a cross that is wrong about
     * a live microphone is a privacy failure rather than a cosmetic one.
     *
     * <p>Fails closed, always. A body that is not JSON, a JSON object with no
     * {@code state}, a state that is not one of the three words the server
     * uses: all of them are {@code unknown}, which the page renders as "no
     * cross and no claim" rather than as "not muted".
     */
    public static String actionState(String body) {
        if (body == null) {
            return "unknown";
        }
        try {
            String state = new JSONObject(body).optString("state", "unknown");
            if ("muted".equals(state) || "unmuted".equals(state)) {
                return state;
            }
        } catch (JSONException malformed) {
            // Fall through: a response this class cannot read says nothing
            // about the mixer.
        }
        return "unknown";
    }

    /**
     * The same payload with the device's {@code battery} object folded in
     * (T5.4).
     *
     * <p>A separate step rather than a third argument to {@link #merge},
     * because the two halves do not share a clock. The server's data arrives on
     * a 60s poll; the battery arrives when Android decides something changed,
     * which may be twice in ten seconds or not for an hour. Folding here lets
     * either event refresh the page with the other's last value still on it,
     * and it keeps {@code merge} answering exactly one question — whether the
     * <em>server</em> gave us a usable pair.
     *
     * <p><b>A bad battery never costs the payload.</b> Everything this method
     * can fail at is a decoration in the corner of a panel whose content is the
     * prices; every failure therefore returns the payload untouched rather than
     * null, which is the opposite of {@code merge}'s all-or-nothing rule and is
     * the right call for the opposite reason. Blanking B3, FX, CRYPTO and
     * WEATHER because a temperature would not parse is not a trade anybody
     * would make.
     *
     * @param payload the merged server payload, or null if the cycle failed
     * @param battery a JSON object literal from {@link BatteryReading}, or null
     *                if no broadcast has arrived yet
     * @return a JSON object literal safe to interpolate into JavaScript, or
     *         null exactly when {@code payload} was null
     */
    public static String withBattery(String payload, String battery) {
        if (payload == null || battery == null) {
            return payload;
        }
        try {
            JSONObject merged = new JSONObject(payload);
            merged.put("battery", new JSONObject(battery));
            return escapeForScript(merged.toString());
        } catch (JSONException malformed) {
            return payload;
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
