"""TT.4 -- the real upstreams, asked for their shape rather than their numbers.

Named `contract_upstream.py` and not `test_*.py` on purpose: the default
discovery pattern is `test*.py`, so `python -m unittest discover -s server/tests
-t .` never picks this file up and `make check` stays offline. Running it is an
explicit act -- `make contract`, or the `-p "contract_*.py"` line in
server/CLAUDE.md -- and even then every case is guarded by RUN_CONTRACT_TESTS,
so a stray discovery pattern cannot open the network either.

**What is asserted is shape, never value.** PETR4's price changes by the
minute and a test that pinned it would be red by lunchtime; the field it
arrives in is what the panel depends on, and that should not change at all.
So each case asks: is the key still there, and is what is in it still a
number. Nothing here asserts a range, a sign, or a count of rows -- a market
holiday must not turn into a failing build.

**A failure here means the fixtures in `tests/fixtures/` are stale.** That is
TT.4 step 5 and it is the whole point of the file: the unit suite is fast and
offline because it reads recorded responses, and recorded responses rot
silently. This is the alarm. Fixing a failure means re-recording the fixture
the message names, then making the normaliser read the new shape -- in that
order, so the unit suite proves the fix.

**The messages name the field.** `assertIn(key, body)` on its own prints two
dicts and leaves the reader to diff them; every helper below spells out the
path that went missing and the fixture to re-record, because this file is run
by hand, months apart, by someone who has forgotten how brapi nests things.

Five upstreams, not the two the task file first listed: crypto and FX moved to
Binance and AwesomeAPI when brapi turned out to charge for them (T3.3 subtask
0), and the moon arrived with T6.13. An upstream the panel calls and this file
does not is an upstream whose schema change reaches the desk as a blank card.
"""
import datetime
import os
import unittest

from server import (
    providers_awesomeapi,
    providers_binance,
    providers_brapi,
    providers_openmeteo,
    providers_usno,
)

SKIP_REASON = "requires network - set RUN_CONTRACT_TESTS=1 (make contract)"


def LIVE(case):
    """Mark a case as needing the network, and skip it unless asked for.

    `skipUnless` rather than a bare `if`, so a run that skips says so in the
    output instead of silently passing an empty file.

    The `needs_network` tag is set unconditionally and the skip only when the
    variable is absent, which is not decoration for its own sake:
    `unittest.skipUnless` is **the identity function when its condition
    holds**, so a guard built out of it alone leaves nothing behind to check
    once RUN_CONTRACT_TESTS is set. A case added to this file without the
    decorator would then be invisible to everything but review -- and it
    would be the one case that opens a socket from `make check`. The tag is
    what `test_contract_helpers` walks the module for.
    """
    case.needs_network = True
    return unittest.skipUnless(os.environ.get("RUN_CONTRACT_TESTS"), SKIP_REASON)(case)

# brapi's four documented free-tier tickers. One symbol per request is what the
# free plan allows, so these are asked for one at a time; see
# providers_brapi.DEFAULT_SYMBOLS_PER_REQUEST for the 400 that proves it.
FREE_SYMBOL = providers_brapi.FREE_TIER_SYMBOLS[0]

# Optional, and read from the environment rather than from config.toml: this
# file is a statement about the upstream, not about one desk's configuration,
# and it must run on a checkout that has no config at all. A paid plan can
# still exercise the same paths by exporting it. Never printed -- the failure
# messages below carry field names, never headers (server/CLAUDE.md).
TOKEN = os.environ.get("BRAPI_TOKEN", "")

# A city that will still exist next year and is not the one in config.example,
# so a geocoding failure cannot be mistaken for a config typo.
GEOCODE_CITY = "Sao Paulo"


class ContractCase(unittest.TestCase):
    """Assertions that name the path they failed on.

    Every helper returns the value it checked, so a caller can descend into a
    nested body without re-reading it out of the dict.
    """

    #: The fixture a subclass's failures should send the reader to re-record.
    fixture = "server/tests/fixtures/"

    def stale(self, path):
        return (
            f"{path} is gone from the live response. The upstream changed its schema: "
            f"re-record {self.fixture} and teach the normaliser the new shape (TT.4 step 5)."
        )

    def obj(self, value, path):
        """`value` is a JSON object."""
        self.assertIsInstance(
            value, dict,
            f"{path} is {type(value).__name__}, expected an object. {self.stale(path)}")
        return value

    def seq(self, value, path):
        """`value` is a non-empty JSON array."""
        self.assertIsInstance(
            value, list,
            f"{path} is {type(value).__name__}, expected an array. {self.stale(path)}")
        self.assertTrue(value, f"{path} is an empty array. {self.stale(path)}")
        return value

    def key(self, body, name, path):
        """`body[name]` exists. The path, not the body, is what the message carries."""
        self.obj(body, path)
        self.assertIn(name, body, self.stale(f"{path}.{name}"))
        return body[name]

    def numeric(self, body, name, path):
        """`body[name]` exists and parses as a float.

        Parses rather than isinstance: brapi sends JSON numbers, Binance and
        AwesomeAPI send the same quantities as strings, and a provider moving
        between the two costs this project nothing -- every normaliser runs
        the value through `float()` anyway. What would cost it is the field
        disappearing, or turning into a dict, which this does catch.
        """
        value = self.key(body, name, path)
        where = f"{path}.{name}"
        self.assertNotIsInstance(value, bool, f"{where} is a bool, expected a number")
        self.assertIsNotNone(value, f"{where} is null, expected a number. {self.stale(where)}")
        try:
            return float(value)
        except (TypeError, ValueError):
            self.fail(f"{where} is {value!r}, which is not a number. {self.stale(where)}")

    def text(self, body, name, path):
        """`body[name]` exists and is a non-empty string."""
        value = self.key(body, name, path)
        where = f"{path}.{name}"
        self.assertIsInstance(
            value, str, f"{where} is {type(value).__name__}, expected a string")
        self.assertTrue(value.strip(), f"{where} is empty, expected a string")
        return value


@LIVE
class BrapiContract(ContractCase):
    """brapi.dev -- B3 stock quotes."""

    fixture = "server/tests/fixtures/brapi_quote_v2.json"

    def test_quote_carries_symbol_and_price(self):
        raw = providers_brapi.fetch([FREE_SYMBOL], token=TOKEN)
        results = self.seq(self.key(raw, "results", "brapi /v2/stocks/quote"), "results")
        entry = self.obj(results[0], "results[0]")

        self.text(entry, "symbol", "results[0]")
        # v2 nests the numbers under `data` and the legacy path is flat;
        # `normalise` reads either, so the contract is "one of the two", and
        # the message has to say which one was looked for or the reader will
        # go hunting in the wrong endpoint.
        values = entry["data"] if isinstance(entry.get("data"), dict) else entry
        self.numeric(values, "regularMarketPrice", "results[0].data")
        self.numeric(values, "regularMarketChangePercent", "results[0].data")

    def test_free_tier_still_answers_without_a_token(self):
        # The one case here that is about access rather than shape. A fresh
        # install has no token and `config.example.toml` promises these four
        # tickers work; brapi moving them behind the paywall would show up on
        # the desk as a B3 card that renders nothing.
        raw = providers_brapi.fetch([FREE_SYMBOL], token="")
        self.seq(self.key(raw, "results", "brapi /v2/stocks/quote, no token"), "results")

    def test_normalise_still_produces_a_row(self):
        quotes = providers_brapi.load([FREE_SYMBOL], token=TOKEN)
        self.assertTrue(
            quotes, "brapi answered but normalise() produced no rows - the shape moved")
        self.assertEqual(set(quotes[0]), {"symbol", "price", "changePct"})

    def test_history_carries_closes(self):
        raw = providers_brapi.fetch_history(FREE_SYMBOL, token=TOKEN, days=30)
        results = self.seq(self.key(raw, "results", "brapi /api/quote"), "results")
        entry = self.obj(results[0], "results[0]")
        points = self.seq(
            self.key(entry, "historicalDataPrice", "results[0]"),
            "results[0].historicalDataPrice")
        self.numeric(self.obj(points[0], "historicalDataPrice[0]"), "close",
                     "results[0].historicalDataPrice[0]")


@LIVE
class BinanceContract(ContractCase):
    """api.binance.com -- crypto, the provider brapi's paywall pushed us to."""

    fixture = "server/tests/fixtures/binance_ticker.json"

    def test_ticker_carries_symbol_price_and_change(self):
        raw = providers_binance.fetch(["BTC"])
        entries = self.seq(raw, "binance /ticker/24hr")
        entry = self.obj(entries[0], "[0]")
        self.text(entry, "symbol", "[0]")
        self.numeric(entry, "lastPrice", "[0]")
        self.numeric(entry, "priceChangePercent", "[0]")

    def test_klines_are_still_arrays_with_the_close_fifth(self):
        # The close is positional and nothing in the response names it, so
        # this is the field most able to move without anyone noticing:
        # Binance inserting a column would silently redraw the sparkline from
        # the high or the volume. `normalise_history` reads index 4.
        raw = providers_binance.fetch_history("BTC", days=5)
        candles = self.seq(raw, "binance /klines")
        first = self.seq(candles[0], "klines[0]")
        self.assertGreater(
            len(first), providers_binance.KLINE_CLOSE,
            f"a kline has {len(first)} columns, and the close is read at index "
            f"{providers_binance.KLINE_CLOSE}. {self.stale('klines[0][4]')}")
        try:
            float(first[providers_binance.KLINE_CLOSE])
        except (TypeError, ValueError):
            self.fail(
                f"klines[0][{providers_binance.KLINE_CLOSE}] is "
                f"{first[providers_binance.KLINE_CLOSE]!r}, not a price. "
                "The column order moved - check Binance's kline layout before trusting "
                "any sparkline.")

    def test_normalise_still_produces_a_row(self):
        crypto = providers_binance.load(["BTC"])
        self.assertTrue(
            crypto, "Binance answered but normalise() produced no rows - the shape moved")
        self.assertEqual(crypto[0]["symbol"], "BTC")


@LIVE
class AwesomeApiContract(ContractCase):
    """economia.awesomeapi.com.br -- FX, likewise."""

    fixture = "server/tests/fixtures/awesomeapi_last.json"

    def test_last_carries_bid_and_change(self):
        raw = providers_awesomeapi.fetch(["USD-BRL"])
        body = self.obj(raw, "awesomeapi /json/last")
        # The response is keyed by the pair with the hyphen removed. That
        # spelling is `to_display_pair`'s input, so a change to it is a change
        # to every row label on the FX card.
        self.assertIn("USDBRL", body, self.stale("last.USDBRL"))
        self.numeric(body["USDBRL"], "bid", "USDBRL")
        self.numeric(body["USDBRL"], "pctChange", "USDBRL")

    def test_daily_history_is_a_list_of_bids(self):
        raw = providers_awesomeapi.fetch_history("USD-BRL", days=5)
        entries = self.seq(raw, "awesomeapi /json/daily")
        self.numeric(self.obj(entries[0], "daily[0]"), "bid", "daily[0]")

    def test_normalise_still_produces_a_row(self):
        fx = providers_awesomeapi.load(["USD-BRL"])
        self.assertTrue(
            fx, "AwesomeAPI answered but normalise() produced no rows - the shape moved")
        self.assertEqual(fx[0]["pair"], "USD/BRL")


@LIVE
class OpenMeteoContract(ContractCase):
    """open-meteo -- geocoding and the forecast, two endpoints on two hosts."""

    fixture = "server/tests/fixtures/openmeteo_forecast.json"

    def test_geocoding_resolves_a_city_to_coordinates(self):
        raw = providers_openmeteo.fetch_geocode(GEOCODE_CITY)
        results = self.seq(
            self.key(raw, "results", "open-meteo /v1/search"), "results")
        first = self.obj(results[0], "results[0]")
        self.numeric(first, "latitude", "results[0]")
        self.numeric(first, "longitude", "results[0]")
        self.text(first, "name", "results[0]")

    def test_forecast_carries_every_field_the_card_reads(self):
        located = providers_openmeteo.normalise_geocode(
            providers_openmeteo.fetch_geocode(GEOCODE_CITY))
        self.assertIsNotNone(located, f"{GEOCODE_CITY} no longer geocodes")
        raw = providers_openmeteo.fetch_forecast(
            located["lat"], located["lon"], "America/Sao_Paulo")

        current = self.obj(
            self.key(raw, "current", "open-meteo /v1/forecast"), "current")
        self.numeric(current, "temperature_2m", "current")
        self.numeric(current, "weather_code", "current")
        self.text(current, "time", "current")
        # is_day is asked for by name in the query string, and T6.13 exists
        # because the panel drew a sun at 21:15 without it. A null here is a
        # legitimate "cannot say" that `_is_day` handles; the key vanishing is
        # not, so this checks presence without demanding a value.
        self.assertIn("is_day", current, self.stale("current.is_day"))

        daily = self.obj(self.key(raw, "daily", "open-meteo /v1/forecast"), "daily")
        for name in ("time", "temperature_2m_max", "temperature_2m_min",
                     "precipitation_probability_max"):
            self.seq(self.key(daily, name, "daily"), f"daily.{name}")

    def test_the_timezone_parameter_still_aligns_the_daily_arrays(self):
        # `_today_index` matches `current.time` against `daily.time` as
        # strings. Without the timezone parameter the daily arrays are cut on
        # UTC days and the match fails after 21:00 in Sao Paulo, which reaches
        # the panel as a missing min and max rather than as an error -- so a
        # None here is the assertion, not a shrug.
        weather, _ = providers_openmeteo.load(GEOCODE_CITY, "America/Sao_Paulo")
        self.assertIsNotNone(
            weather["minC"],
            "daily.time no longer contains current.time's date - the timezone parameter "
            "stopped aligning the arrays, and the card loses its min and max silently")
        self.assertIsNotNone(weather["maxC"], "daily maximum did not resolve for today")
        self.assertIsNotNone(weather["tempC"], "current temperature did not resolve")
        self.assertIsInstance(weather["isDay"], bool)


@LIVE
class UsnoContract(ContractCase):
    """aa.usno.navy.mil -- the moon's primary phases."""

    fixture = "server/tests/fixtures/usno_phases.json"

    def test_phasedata_carries_a_recognised_phase_and_a_date(self):
        raw = providers_usno.fetch_phases()
        entries = self.seq(
            self.key(raw, "phasedata", "usno /api/moon/phases/date"), "phasedata")
        entry = self.obj(entries[0], "phasedata[0]")
        for name in ("year", "month", "day"):
            self.numeric(entry, name, "phasedata[0]")
        self.text(entry, "time", "phasedata[0]")
        phase = self.text(entry, "phase", "phasedata[0]")
        # The four names are a lookup table in `PRIMARY`; an unrecognised one
        # is dropped by `normalise_phases`, so a rename upstream empties the
        # table without raising anything.
        self.assertIn(
            phase, providers_usno.PRIMARY,
            f"phasedata[0].phase is {phase!r}, which providers_usno.PRIMARY does not know. "
            f"Known: {sorted(providers_usno.PRIMARY)}. {self.stale('phasedata[0].phase')}")

    def test_the_window_still_brackets_now_with_two_new_moons(self):
        # LOOKBACK_DAYS and NUMP were tuned so the table has a New Moon on
        # each side of now; `phase_at` returns None when it does not, and the
        # moon simply stops being drawn. The first cut of those two numbers
        # got this wrong, so it is worth asking the live API rather than only
        # the fixture.
        phases = providers_usno.normalise_phases(providers_usno.fetch_phases())
        self.assertTrue(phases, "the USNO answered but no entry survived normalise_phases")
        now = datetime.datetime.now(datetime.timezone.utc)
        self.assertIsNotNone(
            providers_usno.phase_at(phases, now),
            f"the {providers_usno.NUMP} phases from {providers_usno.LOOKBACK_DAYS} days back "
            "no longer bracket now with two New Moons - the panel's moon goes dark")


if __name__ == "__main__":
    unittest.main()
