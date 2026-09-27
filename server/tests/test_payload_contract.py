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
import json
import os
import unittest
from pathlib import Path

from server import actions
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
    "history_interval_s": 21600, "history_days": 30,
    "actions": ["mute-audio", "mute-mic"],
}

ROWS = {
    "quotes": [{"symbol": "PETR4", "price": 48.5, "changePct": -0.23}],
    "fx": [{"pair": "USD/BRL", "rate": 5.14, "changePct": 0.36}],
    "crypto": [{"symbol": "BTC", "price": 81470.0, "changePct": 1.01}],
}

HISTORY = {"PETR4": [47.0, 47.8, 48.5], "USD/BRL": [5.1, 5.12, 5.14],
           "BTC": [80000.0, 80900.0, 81470.0]}

WEATHER = {"tempC": 24, "minC": 18, "maxC": 27, "code": 3, "isDay": True,
           "city": "São Paulo", "rainChance": 20}

MOON = {"phase": "waxing gibbous", "illumination": 0.71, "source": "usno"}


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

    originals = []

    def patch(module, name, value):
        originals.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    try:
        for name, market in (("providers_brapi", "quotes"),
                             ("providers_awesomeapi", "fx"),
                             ("providers_binance", "crypto")):
            module = getattr(server_module, name)
            patch(module, "load", lambda *a, _m=market, **k: list(ROWS[_m]))
            patch(module, "load_history", lambda *a, _m=market, **k: {
                row[key_of(_m)]: HISTORY[row[key_of(_m)]] for row in ROWS[_m]})

        openmeteo = server_module.providers_openmeteo
        patch(openmeteo, "fetch_geocode", lambda *a, **k: {})
        patch(openmeteo, "normalise_geocode",
              lambda *a, **k: {"lat": -23.55, "lon": -46.63, "city": "São Paulo"})
        patch(openmeteo, "fetch_forecast", lambda *a, **k: {})
        patch(openmeteo, "normalise", lambda *a, **k: dict(WEATHER))

        usno = server_module.providers_usno
        patch(usno, "moon_phase", lambda *a, **k: dict(MOON))
        patch(usno, "synodic_phase", lambda *a, **k: dict(MOON))

        app = App(dict(CONFIG), clock=FakeClock())
        # The sparklines, primed **synchronously**. `warm_history()` is the
        # production path and starts a thread per market on purpose -- a
        # sparkline must never make a payload wait -- but a fixture generated
        # against a thread is a fixture that is sometimes written without its
        # histories, and the difference would be invisible in the diff. Same
        # producer, same cache, no thread.
        for market in app.history_caches:
            app.history_caches[market].get(
                app.clock(), CONFIG["history_interval_s"], app._history_producer(market))
        return {"quotes": app.quotes(), "weather": app.weather()}
    finally:
        for module, name, value in reversed(originals):
            setattr(module, name, value)


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
            {"quotes", "fx", "crypto", "stale", "theme", "language", "night", "actions"})

    def test_the_rows_carry_their_history(self):
        # A fixture with empty sparklines would let the Android and web
        # assertions pass against a shape the panel never sees.
        rows = build()["quotes"]["quotes"]
        self.assertTrue(rows[0]["history"], "the fixture's rows have no history")

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
