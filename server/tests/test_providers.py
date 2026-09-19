"""TT.2 -- the provider normalisers, from recorded fixtures, with no network.

Every fixture in `fixtures/` is a real response, captured 2026-09-19 from the
upstream it is named for. That matters more than it sounds: the shapes these
tests pin were established by asking the APIs (T3.3 subtask 0), not by reading
documentation that turned out not to describe crypto or FX at all.

The outbound call is never made here. Each provider takes its `get` as an
argument for exactly this reason, so a test replaces one function and nothing
in `upstream.py` is reached -- see server/CLAUDE.md, "unit tests must never
touch the network".
"""
import json
import unittest
from pathlib import Path

from server import providers_awesomeapi, providers_binance, providers_brapi, providers_openmeteo

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def recorded(name):
    """A `get` that ignores the URL and returns a fixture.

    The URL is asserted separately, by the tests that care, rather than here:
    a stub that checked it would make every test fail for one reason.
    """
    return lambda url, headers=None, timeout=None: fixture(name)


class BrapiTests(unittest.TestCase):
    def test_v2_shape_normalises(self):
        quotes = providers_brapi.normalise(fixture("brapi_quote_v2.json"))
        self.assertEqual([q["symbol"] for q in quotes], ["PETR4", "VALE3"])
        for quote in quotes:
            self.assertIsInstance(quote["price"], float)
            self.assertIsInstance(quote["changePct"], float)
            self.assertEqual(set(quote), {"symbol", "price", "changePct"})

    def test_legacy_flat_shape_normalises_identically(self):
        # brapi serves both shapes, at two paths, and both answered 200
        # without a token on the same day. A reader who assumed one would
        # produce an empty panel against the other.
        v2 = providers_brapi.normalise(fixture("brapi_quote_v2.json"))
        legacy = providers_brapi.normalise(fixture("brapi_quote_legacy.json"))
        self.assertEqual([q["symbol"] for q in v2], [q["symbol"] for q in legacy])

    def test_entry_without_a_price_is_skipped_not_fatal(self):
        raw = {"results": [
            {"symbol": "GOOD", "data": {"regularMarketPrice": 1.5,
                                        "regularMarketChangePercent": 2.0}},
            {"symbol": "DELISTED", "data": {}},
            {"symbol": "JUNK"},
        ]}
        quotes = providers_brapi.normalise(raw)
        self.assertEqual([q["symbol"] for q in quotes], ["GOOD"])

    def test_missing_change_becomes_zero_not_none(self):
        # format.js renders a number; None would print as "null%".
        raw = {"results": [{"symbol": "X", "data": {"regularMarketPrice": 10}}]}
        self.assertEqual(providers_brapi.normalise(raw)[0]["changePct"], 0.0)

    def test_garbage_input_returns_empty_list(self):
        # A non-empty list is the one that matters: an upstream answering with
        # a JSON array -- a proxy, a captive portal, a changed error envelope
        # -- used to raise AttributeError here, and an exception out of a
        # normaliser is not an UpstreamError, so it escaped the cache entirely.
        # The empty list passed the old guard only because it is falsy.
        for raw in (None, {}, {"results": None}, {"results": "nope"}, [],
                    [{"symbol": "X"}], "a string", 7):
            self.assertEqual(providers_brapi.normalise(raw), [])

    def test_fetch_builds_the_documented_url_and_sends_no_empty_header(self):
        seen = {}

        def get(url, headers=None, timeout=None):
            seen["url"] = url
            seen["headers"] = headers
            return {"results": []}

        providers_brapi.fetch(["PETR4", "VALE3"], token="", get=get)
        self.assertEqual(seen["url"], providers_brapi.QUOTE_URL + "?symbols=PETR4,VALE3")
        # No Authorization header at all without a token, rather than an empty
        # Bearer, which brapi would reject differently from an absent one.
        self.assertEqual(seen["headers"], {})

    def test_token_goes_in_the_header_never_the_query(self):
        seen = {}

        def get(url, headers=None, timeout=None):
            seen["url"] = url
            seen["headers"] = headers
            return {"results": []}

        providers_brapi.fetch(["PETR4"], token="sekrit", get=get)
        self.assertNotIn("sekrit", seen["url"])
        self.assertEqual(seen["headers"], {"Authorization": "Bearer sekrit"})

    def test_no_symbols_makes_no_call(self):
        def explode(*args, **kwargs):
            raise AssertionError("fetch called with nothing to ask for")

        self.assertEqual(providers_brapi.fetch([], get=explode), {"results": []})


class BinanceTests(unittest.TestCase):
    def test_fixture_normalises_to_bare_coins(self):
        crypto = providers_binance.normalise(fixture("binance_ticker.json"))
        self.assertEqual([c["symbol"] for c in crypto], ["BTC", "ETH"])
        for entry in crypto:
            # Binance sends every number as a string; the panel needs floats.
            self.assertIsInstance(entry["price"], float)
            self.assertIsInstance(entry["changePct"], float)

    def test_pair_round_trip(self):
        self.assertEqual(providers_binance.to_pair("BTC"), "BTCUSDT")
        self.assertEqual(providers_binance.to_pair("btc"), "BTCUSDT")
        # Already a pair: left alone, so a config spelling it out still works.
        self.assertEqual(providers_binance.to_pair("BTCUSDT"), "BTCUSDT")
        self.assertEqual(providers_binance.to_coin("BTCUSDT"), "BTC")
        self.assertEqual(providers_binance.to_coin("BTC"), "BTC")

    def test_symbols_parameter_is_json_and_cannot_be_broken_out_of(self):
        seen = {}

        def get(url, headers=None, timeout=None):
            seen["url"] = url
            return []

        providers_binance.fetch(['BTC"],["'], get=get)
        # The quote is escaped by json.dumps rather than terminating the array.
        self.assertIn('\\"', seen["url"])
        self.assertTrue(seen["url"].startswith(providers_binance.TICKER_URL + "?symbols="))

    def test_garbage_input_returns_empty_list(self):
        for raw in (None, {}, "nope", [None, 3, "x"]):
            self.assertEqual(providers_binance.normalise(raw), [])


class AwesomeApiTests(unittest.TestCase):
    def test_fixture_normalises_to_slashed_pairs(self):
        fx = providers_awesomeapi.normalise(fixture("awesomeapi_last.json"),
                                            pairs=["USD-BRL", "EUR-BRL"])
        self.assertEqual([f["pair"] for f in fx], ["USD/BRL", "EUR/BRL"])
        for entry in fx:
            self.assertIsInstance(entry["rate"], float)
            self.assertIsInstance(entry["changePct"], float)

    def test_no_hyphen_ever_reaches_the_payload(self):
        # A task-file rule, and the reason is legibility: "USD-BRL" on a panel
        # reads as a subtraction.
        fx = providers_awesomeapi.normalise(fixture("awesomeapi_last.json"),
                                            pairs=["USD-BRL", "EUR-BRL"])
        self.assertNotIn("-", json.dumps(fx))

    def test_rate_is_bid_not_ask(self):
        raw = {"USDBRL": {"bid": "5.1434", "ask": "5.1438", "pctChange": "0.3"}}
        self.assertEqual(providers_awesomeapi.normalise(raw)[0]["rate"], 5.1434)

    def test_row_order_follows_config_not_the_upstream(self):
        raw = fixture("awesomeapi_last.json")
        fx = providers_awesomeapi.normalise(raw, pairs=["EUR-BRL", "USD-BRL"])
        self.assertEqual([f["pair"] for f in fx], ["EUR/BRL", "USD/BRL"])

    def test_unrequested_rows_survive_after_the_configured_ones(self):
        # Visible beats silently dropped: a row nobody asked for is a question,
        # a row that vanished is not.
        raw = {"USDBRL": {"bid": "5.0", "pctChange": "0"},
               "GBPBRL": {"bid": "6.0", "pctChange": "0"}}
        fx = providers_awesomeapi.normalise(raw, pairs=["USD-BRL"])
        self.assertEqual([f["pair"] for f in fx], ["USD/BRL", "GBP/BRL"])

    def test_every_config_spelling_reaches_the_same_request(self):
        for spelling in ("USD-BRL", "USD/BRL", "USDBRL", "usd-brl"):
            self.assertEqual(providers_awesomeapi.to_request_pair(spelling), "USD-BRL")

    def test_garbage_input_returns_empty_list(self):
        for raw in (None, [], "nope", {"USDBRL": "not a dict"}):
            self.assertEqual(providers_awesomeapi.normalise(raw), [])


class OpenMeteoTests(unittest.TestCase):
    def test_geocode_fixture_resolves_and_keeps_the_upstream_spelling(self):
        located = providers_openmeteo.normalise_geocode(fixture("openmeteo_geocode.json"))
        self.assertAlmostEqual(located["lat"], -23.5475, places=3)
        self.assertAlmostEqual(located["lon"], -46.636, places=2)
        # "Sao Paulo" went out, "São Paulo" came back: showing what was
        # actually found is how a human notices the wrong Springfield.
        self.assertEqual(located["city"], "São Paulo")

    def test_geocode_with_no_results_is_none_not_an_exception(self):
        for raw in (None, {}, {"results": []}, {"results": "nope"},
                    [{"a": 1}], "a string"):
            self.assertIsNone(providers_openmeteo.normalise_geocode(raw))

    def test_a_list_body_normalises_to_empty_rather_than_raising(self):
        weather = providers_openmeteo.normalise([1, 2])
        self.assertIsNone(weather["tempC"])
        self.assertEqual(set(weather), {"tempC", "minC", "maxC", "code", "city"})

    def test_forecast_fixture_normalises_to_the_contract_shape(self):
        weather = providers_openmeteo.normalise(fixture("openmeteo_forecast.json"),
                                                city="São Paulo")
        self.assertEqual(set(weather), {"tempC", "minC", "maxC", "code", "city"})
        self.assertIsInstance(weather["tempC"], float)
        self.assertIsInstance(weather["code"], int)

    def test_today_is_matched_by_date_not_taken_from_index_zero(self):
        # The bug this guards is the one T3.4 warns about: without the
        # timezone parameter the daily arrays are cut on UTC days, so after
        # 21:00 in Sao Paulo index 0 is already tomorrow and the panel shows
        # tomorrow's high as today's. A wrong number, not an error.
        raw = {
            "current": {"time": "2026-09-20T11:15", "temperature_2m": 24.0,
                        "weather_code": 2},
            "daily": {"time": ["2026-09-19", "2026-09-20"],
                      "temperature_2m_max": [99.0, 26.6],
                      "temperature_2m_min": [98.0, 17.4]},
        }
        weather = providers_openmeteo.normalise(raw)
        self.assertEqual(weather["maxC"], 26.6)
        self.assertEqual(weather["minC"], 17.4)

    def test_a_day_that_does_not_match_gives_none_rather_than_a_guess(self):
        raw = {
            "current": {"time": "2026-12-25T11:15", "temperature_2m": 24.0},
            "daily": {"time": ["2026-09-19"], "temperature_2m_max": [26.1],
                      "temperature_2m_min": [15.5]},
        }
        weather = providers_openmeteo.normalise(raw)
        self.assertIsNone(weather["maxC"])
        self.assertIsNone(weather["minC"])
        # The current reading is independent of the daily alignment and
        # survives it.
        self.assertEqual(weather["tempC"], 24.0)

    def test_missing_values_are_none_never_zero(self):
        # Zero is a real temperature in most of the world, so a zero standing
        # in for "no data" is a lie the panel cannot detect.
        weather = providers_openmeteo.normalise({})
        self.assertIsNone(weather["tempC"])
        self.assertIsNone(weather["code"])

    def test_forecast_url_carries_the_configured_timezone(self):
        seen = {}

        def get(url, headers=None, timeout=None):
            seen["url"] = url
            return {}

        providers_openmeteo.fetch_forecast(-23.5, -46.6, "Europe/Lisbon", get=get)
        self.assertIn("timezone=Europe%2FLisbon", seen["url"])

    def test_load_skips_the_geocode_when_coordinates_are_cached(self):
        calls = []

        def get(url, headers=None, timeout=None):
            calls.append(url)
            return fixture("openmeteo_forecast.json")

        coords = {"lat": -23.5, "lon": -46.6, "city": "São Paulo"}
        providers_openmeteo.load("Sao Paulo", "America/Sao_Paulo", coords=coords, get=get)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("geocoding-api", calls[0])

    def test_load_raises_for_a_city_that_does_not_resolve(self):
        def get(url, headers=None, timeout=None):
            return {"results": []}

        with self.assertRaises(providers_openmeteo.UpstreamError):
            providers_openmeteo.load("Atlantis", "UTC", get=get)


if __name__ == "__main__":
    unittest.main()
