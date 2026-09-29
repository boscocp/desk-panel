"""The payload's shape, written down once and read by three layers.

The shape of what the panel renders exists in four places and, until T10.1,
nothing compared any of them:

  1. `web/js/mock.js`          - what a browser-only contributor develops against
  2. `App.quotes()`/`weather()` - what the PC actually sends
  3. `DataPayload.merge`        - what reaches the page, rebuilt key by key
  4. `DataPayloadTest`'s own string literal

`merge` rebuilds the payload key by key, so **a key added to the server and
not to that method does not reach the phone** - silently, with a correct
server and a correct page. It shipped twice: `night` in T6.4 and `actions` in
T8.2, the second time with a comment in the file warning about the first.
`App.weather`'s own docstring calls it "the three-edit trap".

This file is the description those four copies are checked against. It writes
`fixtures/payload.json` from **the server's own assembly** - not by hand, or
it would be a fifth copy with better branding - and the other two layers read
that file:

  - `android/.../DataPayloadTest` asserts `merge` preserves every top-level
    key of the `/quotes` body, rather than the handful somebody remembered.
  - `web/test/payload_contract.test.js` asserts `mock.js` feeds the page the
    same key set the PC sends.

Regenerate after a deliberate change:

    DESK_PANEL_WRITE_FIXTURES=1 python -m unittest server.tests.test_payload_contract

and commit the result, which is the moment the other two layers go red if they
have not been taught the new key.
"""
import datetime
import json
import contextlib
import os
import tempfile
import unittest
from pathlib import Path

from server import actions
from server import providers_openmeteo, providers_usno
from server.server import App

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = FIXTURES / "payload.json"
ACTION_IDS = FIXTURES / "action_ids.json"

WRITE = os.environ.get("DESK_PANEL_WRITE_FIXTURES") == "1"

# Fixed values everywhere: a fixture regenerated from a live clock or a live
# upstream would differ on every run and teach everyone to re-commit it
# without reading the diff.
CONFIG = {
    "quotes": ["PETR4"], "fx": ["USD-BRL"], "crypto": ["BTC"],
    "city": "São Paulo", "timezone": "America/Sao_Paulo",
    "theme": "neon", "language": "pt-BR",
    "night_start": "23:00", "night_end": "06:00",
    "quotes_interval_s": 300, "weather_interval_s": 900, "brapi_token": "",
    "history_interval_s": 21600, "history_days": 30, "moon_interval_s": 21600,
    "actions": ["mute-audio", "mute-mic"],
    # Two accounts, one per provider, so the description carries both
    # normalisers' output merged -- the part of the agenda worth describing.
    "calendar_accounts": [{"provider": "google", "name": "personal"},
                          {"provider": "microsoft", "name": "work"}],
    "google_client_id": "fixture.apps.googleusercontent.com",
    "google_client_secret": "not-a-secret",
    "microsoft_client_id": "00000000-0000-0000-0000-000000000000",
    "calendar_interval_s": 300, "calendar_lookahead_h": 24,
    "calendar_show_titles": True,
}

ROWS = {
    "quotes": [{"symbol": "PETR4", "price": 48.5, "changePct": -0.23}],
    "fx": [{"pair": "USD/BRL", "rate": 5.14, "changePct": 0.36}],
    "crypto": [{"symbol": "BTC", "price": 81470.0, "changePct": 1.01}],
}

HISTORY = {"PETR4": [47.0, 47.8, 48.5], "USD/BRL": [5.1, 5.12, 5.14],
           "BTC": [80000.0, 80900.0, 81470.0]}

# The weather half is patched at the **fetch** seam, not at `normalise`.
#
# That distinction is the whole point of the file and the first cut got it
# wrong: `App.weather()` contributes only `stale` and `moon`, so every other
# key of the weather object is decided by `providers_openmeteo.normalise`.
# Replacing *that* produced a description carrying `rainChance` and no
# `precipProb` -- a shape no server has ever sent, in the file whose own
# header calls itself the one description of the payload. Worse, a key added
# to `normalise` would have regenerated to exactly the same bytes. So the
# canned bodies below are raw upstream responses (measured shapes, see that
# module's docstring) and the real `normalise`/`normalise_geocode` run on
# them.
RAW_GEOCODE = {"results": [{"name": "São Paulo", "latitude": -23.5475,
                            "longitude": -46.63611,
                            "timezone": "America/Sao_Paulo"}]}

# `daily` is a week and `normalise` picks the day matching `current.time`,
# never index 0 -- so the arrays carry three days and the answer is the
# middle one. A generator that fed a single day would agree with a broken
# `_today_index` as readily as with a working one.
RAW_FORECAST = {
    "current": {"time": "2026-09-22T00:27", "temperature_2m": 24.0,
                "weather_code": 3, "is_day": 1},
    "daily": {"time": ["2026-09-21", "2026-09-22", "2026-09-23"],
              "temperature_2m_max": [25.0, 27.0, 28.0],
              "temperature_2m_min": [16.0, 18.0, 19.0],
              "precipitation_probability_max": [10, 20, 30]},
}

# The moon, from the project's own arithmetic at a fixed instant rather than
# from a dict typed here: `synodic_phase` and `moon_phase` return the same
# five keys (both go through `_describe`), and a hand-written stand-in was
# already wrong about three of them. Only the provenance is overridden, to
# the one a reachable USNO reports.
MOON_WHEN = datetime.datetime(2026, 9, 22, 0, 27, tzinfo=datetime.timezone.utc)
MOON = dict(providers_usno.synodic_phase(MOON_WHEN), source="usno")


# The calendars are patched at the fetch seam, like the weather, so the two
# real normalisers and `select` decide the shape. The raw bodies are the
# recorded ones the provider tests read.
RAW_GOOGLE = json.loads((FIXTURES / "google_events.json").read_text(encoding="utf-8"))
RAW_GRAPH = json.loads((FIXTURES / "graph_calendarview.json").read_text(encoding="utf-8"))
AGENDA_NOW = datetime.datetime(2026, 9, 22, 9, 0, tzinfo=datetime.timezone.utc)


def fake_token_post(url, fields):
    """Every token endpoint, answering a refresh with a read-only grant."""
    if "googleapis" in url:
        scope = "https://www.googleapis.com/auth/calendar.events.owned.readonly"
    else:
        scope = "https://graph.microsoft.com/Calendars.ReadBasic"
    return {"access_token": "fixture-access", "expires_in": 3600, "scope": scope,
            "token_type": "Bearer"}


class FakeClock:
    def __call__(self):
        return 0.0


def build():
    """Both halves of the payload, from the server's own assembly.

    Every provider is replaced, so this reaches no network and produces the
    same bytes on every machine. What is *not* replaced is any of `App` -- the
    caching, the history attachment, the stale flag and the four keys that
    ride `/quotes` are the real code, which is the only reason the file it
    writes is worth anything.
    """
    import server.server as server_module

    with contextlib.ExitStack() as undo:
        def patch(module, name, value):
            undo.callback(setattr, module, name, getattr(module, name))
            setattr(module, name, value)

        for name, market in (("providers_brapi", "quotes"),
                             ("providers_awesomeapi", "fx"),
                             ("providers_binance", "crypto")):
            module = getattr(server_module, name)
            patch(module, "load", lambda *a, _m=market, **k: list(ROWS[_m]))
            patch(module, "load_history", lambda *a, _m=market, **k: {
                row[key_of(_m)]: HISTORY[row[key_of(_m)]] for row in ROWS[_m]})

        # Only the two network calls. `normalise` and `normalise_geocode` are
        # the code that decides the weather object's shape and they run for
        # real -- see the comment on RAW_FORECAST above.
        openmeteo = server_module.providers_openmeteo
        patch(openmeteo, "fetch_geocode", lambda *a, **k: dict(RAW_GEOCODE))
        patch(openmeteo, "fetch_forecast", lambda *a, **k: dict(RAW_FORECAST))

        usno = server_module.providers_usno
        patch(usno, "moon_phase", lambda *a, **k: dict(MOON))
        patch(usno, "synodic_phase", lambda *a, **k: dict(MOON))

        calendar = server_module.providers_calendar
        patch(calendar, "fetch_google", lambda *a, **k: dict(RAW_GOOGLE))
        patch(calendar, "fetch_graph", lambda *a, **k: dict(RAW_GRAPH))

        tokens = undo.enter_context(tempfile.TemporaryDirectory())
        store = Path(tokens) / "calendar-tokens.json"
        store.write_text(json.dumps({
            "google/personal": {"refresh_token": "fixture-google"},
            "microsoft/work": {"refresh_token": "fixture-microsoft"},
        }), encoding="utf-8")

        app = App(dict(CONFIG), clock=FakeClock(), tokens_path=store,
                  wall_clock=lambda: AGENDA_NOW, oauth_post=fake_token_post)
        # Primed synchronously for the reason the moon is, below: the
        # production path is a background thread, and a fixture written
        # against a thread is sometimes written without its events.
        app.agenda_cache.get(app.clock(), CONFIG["calendar_interval_s"], app._produce_agenda)
        # The sparklines, primed **synchronously**. `warm_history()` is the
        # production path and starts a thread per market on purpose -- a
        # sparkline must never make a payload wait -- but a fixture generated
        # against a thread is a fixture that is sometimes written without its
        # histories, and the difference would be invisible in the diff. Same
        # producer, same cache, no thread.
        for market in app.history_caches:
            app.history_caches[market].get(
                app.clock(), CONFIG["history_interval_s"], app._history_producer(market))
        # And the moon, for the same reason and one more. `App.weather()`
        # starts a background refresh whenever the moon cache is cold, and
        # that thread resolves `providers_usno.moon_phase` *itself* -- while
        # the ExitStack is putting the real one back. Losing that race
        # costs a live request to the USNO from a test whose whole claim is
        # that it reaches no network, and `_refresh_moon_async` swallows the
        # failure, so the only symptom is a slow suite. Priming it here means
        # the cache is fresh, no thread is started, and the payload's `moon`
        # comes from the production branch rather than from the fallback.
        app.moon_cache.get(app.clock(), CONFIG["moon_interval_s"], usno.moon_phase)
        return {"quotes": app.quotes(), "weather": app.weather()}


def key_of(market):
    return "pair" if market == "fx" else "symbol"


class PayloadFixtureTests(unittest.TestCase):
    """The committed description, and that it still matches the server."""

    def test_the_fixture_matches_what_the_server_assembles(self):
        produced = build()
        if WRITE:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            PAYLOAD.write_text(json.dumps(with_readme(produced), indent=2,
                                          sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertTrue(PAYLOAD.is_file(),
                        f"{PAYLOAD} is missing; regenerate with "
                        "DESK_PANEL_WRITE_FIXTURES=1")
        committed = json.loads(PAYLOAD.read_text(encoding="utf-8"))
        committed.pop("_readme", None)
        self.assertEqual(
            committed, produced,
            "the committed payload description no longer matches what this server "
            "builds. Regenerate with DESK_PANEL_WRITE_FIXTURES=1 and commit it -- "
            "and expect the Android and web tests that read it to go red until "
            "they are taught the change.")

    def test_the_description_carries_every_key_quotes_sends(self):
        # The assertion the other two layers depend on. Written here as well
        # so a fixture that lost a key fails in the layer that produced it.
        produced = build()["quotes"]
        self.assertEqual(
            set(produced),
            {"quotes", "fx", "crypto", "stale", "theme", "language", "night", "actions", "agenda"})

    def test_the_rows_carry_their_history(self):
        # A fixture with empty sparklines would let the Android and web
        # assertions pass against a shape the panel never sees.
        rows = build()["quotes"]["quotes"]
        self.assertTrue(rows[0]["history"], "the fixture's rows have no history")

    def test_the_generator_is_deterministic(self):
        # The file is committed and compared, so a generator that answered
        # differently on a second run would turn every unrelated wave into a
        # fixture diff nobody reads. Three runs rather than two, because the
        # failure this guards against was a background thread that usually
        # won.
        first = build()
        self.assertEqual(first, build())
        self.assertEqual(first, build())

    def test_the_weather_half_is_the_shape_normalise_produces(self):
        # The assertion the first cut of this file needed and did not have.
        # Every key of the weather object except `stale` and `moon` comes from
        # `providers_openmeteo.normalise`, so the description is held to that
        # function rather than to a dict typed in this file -- which is how it
        # came to carry `rainChance`, a key no server sends, instead of
        # `precipProb`, which every server does.
        produced = build()["weather"]
        expected = set(providers_openmeteo.normalise({})) | {"stale", "moon"}
        self.assertEqual(set(produced), expected)

    def test_the_moon_carries_the_keys_the_provider_returns(self):
        # Same argument one level down: `moon_phase` and `synodic_phase` both
        # return `_describe`'s five keys, and a stand-in written by hand was
        # wrong about three of them (`illumination` for `illum`, a space for
        # the hyphen in the phase name, and no age at all).
        self.assertEqual(set(build()["weather"]["moon"]),
                         set(providers_usno.synodic_phase(MOON_WHEN)))

    def test_the_moon_rides_inside_weather(self):
        # `App.weather`'s docstring explains why: the Android side copies the
        # weather object whole, so a key added there needs no Java change --
        # unlike a key at the payload's top level, which is the trap this
        # whole file exists to close.
        self.assertIn("moon", build()["weather"])


class ActionIdFixtureTests(unittest.TestCase):
    """The second list written in three languages.

    `actions.CATALOGUE` (Python), `Actions.ALLOWED` (Java) and
    `words.actions` (JavaScript) are three copies of one list, and nothing
    compared them either: a half-added action draws no button, or draws one
    the bridge refuses. The duplication itself stays -- ADR 0015 wants the
    phone's allowlist independent of the server's, so a compromised asset
    cannot widen what the bridge will send. Only the absence of a check that
    they agree was the defect.
    """

    def test_the_fixture_matches_the_catalogue(self):
        produced = {"catalogue": list(actions.CATALOGUE)}
        if WRITE:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            ACTION_IDS.write_text(json.dumps(with_readme(produced), indent=2,
                                             sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertTrue(ACTION_IDS.is_file(),
                        f"{ACTION_IDS} is missing; regenerate with "
                        "DESK_PANEL_WRITE_FIXTURES=1")
        committed = json.loads(ACTION_IDS.read_text(encoding="utf-8"))
        committed.pop("_readme", None)
        self.assertEqual(
            committed, produced,
            "the action catalogue changed and the committed list did not. "
            "Regenerate with DESK_PANEL_WRITE_FIXTURES=1 -- the Java allowlist "
            "and the page's words are checked against this file and will go red "
            "until they carry the new id too.")


def with_readme(payload):
    """The generated file says so, in the file, to whoever opens it first."""
    return dict(
        payload,
        _readme=(
            "Generated by server/tests/test_payload_contract.py from the server's "
            "own assembly. Do not edit by hand: regenerate with "
            "DESK_PANEL_WRITE_FIXTURES=1 python -m unittest "
            "server.tests.test_payload_contract. It is the one description of the "
            "payload shape; the Android and web suites read this file so that a "
            "key added on the PC and forgotten on the phone fails a test instead "
            "of vanishing in silence (T10.1)."))


if __name__ == "__main__":
    unittest.main()
