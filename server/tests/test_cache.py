"""TT.2 -- the cache, the stale fallback, and the payloads built on them.

No network, no sleeping. `TimedCache` takes `now` as an argument and `App`
takes its clock, so an hour passes here in a function call. A test that
slept for a 300s TTL would be a test nobody runs.

What is actually being pinned is a product decision from T3.3 step 5: an
upstream that has gone away must cost the panel its freshness, never its
contents. The panel showing a slightly old price beats the panel showing
nothing, and `stale` is how the page knows to say so.
"""
import contextlib
import io
import unittest

from server import providers_openmeteo, providers_usno
from server.server import App, TimedCache, action_id, route
from server.upstream import UpstreamError


class TimedCacheTests(unittest.TestCase):
    def test_first_call_produces_and_is_not_stale(self):
        cache = TimedCache()
        value, stale = cache.get(0, 300, lambda: "fresh")
        self.assertEqual(value, "fresh")
        self.assertFalse(stale)

    def test_inside_the_ttl_the_producer_is_not_called_again(self):
        cache = TimedCache()
        calls = []

        def produce():
            calls.append(1)
            return len(calls)

        cache.get(0, 300, produce)
        cache.get(299, 300, produce)
        self.assertEqual(len(calls), 1, "a cached value was refetched inside its TTL")

    def test_at_the_ttl_boundary_it_refreshes(self):
        # Exactly at the TTL counts as expired: `now - fetched_at < ttl`. The
        # boundary is asserted because an off-by-one here is invisible in
        # normal running and doubles the request count against a 15k/month
        # free tier.
        cache = TimedCache()
        calls = []

        def produce():
            calls.append(1)
            return len(calls)

        cache.get(0, 300, produce)
        cache.get(300, 300, produce)
        self.assertEqual(len(calls), 2)

    def test_a_failed_refresh_serves_the_last_good_value_and_flags_it(self):
        cache = TimedCache()
        cache.get(0, 300, lambda: "good")

        def fail():
            raise UpstreamError("upstream down")

        value, stale = cache.get(1000, 300, fail)
        self.assertEqual(value, "good", "a failed refresh threw away the last good value")
        self.assertTrue(stale)

    def test_a_failure_on_a_cold_start_is_stale_rather_than_an_exception(self):
        cache = TimedCache()

        def fail():
            raise UpstreamError("upstream down")

        value, stale = cache.get(0, 300, fail)
        self.assertIsNone(value)
        self.assertTrue(stale)

    def test_recovery_clears_the_stale_flag(self):
        cache = TimedCache()
        cache.get(0, 300, lambda: "good")

        def fail():
            raise UpstreamError("down")

        cache.get(1000, 300, fail)
        value, stale = cache.get(2000, 300, lambda: "better")
        self.assertEqual(value, "better")
        self.assertFalse(stale)

    def test_a_failure_does_not_hammer_the_upstream_every_request(self):
        # After a failure the value is still held, so the next call inside the
        # TTL must not retry -- otherwise a dead upstream turns into one
        # outbound request per panel poll, which is the opposite of what the
        # cache is for.
        cache = TimedCache()
        cache.get(0, 300, lambda: "good")
        calls = []

        def fail():
            calls.append(1)
            raise UpstreamError("down")

        cache.get(1000, 300, fail)
        cache.get(1001, 300, fail)
        self.assertEqual(len(calls), 1)

    def test_a_cold_failure_does_not_hammer_the_upstream_either(self):
        # The warm case below was covered and the cold one was not, and the
        # cold one is the realistic failure: a PC that boots before its router
        # does. `fresh_at` used to require a non-None value, so a cache that
        # had never succeeded was never fresh and retried on every request --
        # three outbound calls per panel poll, for ever.
        cache = TimedCache()
        calls = []

        def fail():
            calls.append(1)
            raise UpstreamError("down")

        for now in range(5):
            cache.get(now, 300, fail)
        self.assertEqual(len(calls), 1)

    def test_a_cold_failure_still_retries_once_the_ttl_is_spent(self):
        cache = TimedCache()
        calls = []

        def fail():
            calls.append(1)
            raise UpstreamError("down")

        cache.get(0, 300, fail)
        cache.get(300, 300, fail)
        self.assertEqual(len(calls), 2)

    def test_concurrent_callers_share_one_refresh(self):
        # Requests are served on threads now, so two polls landing together
        # must not each start the same fetch.
        import threading

        cache = TimedCache()
        calls = []
        started = threading.Barrier(4)

        def produce():
            calls.append(1)
            return "value"

        def worker():
            started.wait()
            cache.get(0, 300, produce)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        started.wait()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(calls), 1)

    def test_only_upstream_errors_are_swallowed(self):
        # A bug in a normaliser must not be laundered into "stale". Anything
        # that is not an UpstreamError is a defect in this repository, and it
        # should reach the log as a traceback.
        cache = TimedCache()

        def bug():
            raise ZeroDivisionError("a real bug")

        with self.assertRaises(ZeroDivisionError):
            cache.get(0, 300, bug)


def history_providers():
    """Every provider module in `server.server` that can fetch a history.

    Discovered rather than listed, because a hand-written list is exactly what
    went stale three times: a provider gains a `load_history`, the stub list
    does not, and the unit suite quietly starts fetching thirty daily closes
    from a real upstream. Nothing failed -- the only symptom was the runtime
    going up -- which is the worst kind of test bug, because the suite still
    says OK.
    """
    import server.server as server_module

    return [
        getattr(server_module, name)
        for name in dir(server_module)
        if name.startswith("providers_")
        and hasattr(getattr(server_module, name), "load_history")
    ]


class NoNetworkGuardTests(unittest.TestCase):
    """The rule in server/CLAUDE.md, enforced rather than trusted.

    `unshare -n` proves the suite *passes* without a network; it cannot prove
    the suite never *reaches* for one, because a refused connection and a
    stubbed one both end in a green run. This watches the socket instead.
    """

    def test_building_a_payload_opens_no_outbound_socket(self):
        import socket

        import server.server as server_module

        opened = []
        real_connect = socket.socket.connect

        def guarded(sock, address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else address
            if host not in ("127.0.0.1", "::1", "localhost"):
                opened.append(host)
                raise AssertionError(f"outbound connect to {host}")
            return real_connect(sock, address, *args, **kwargs)

        for module in history_providers():
            self.addCleanup(setattr, module, "load_history", module.load_history)
            module.load_history = lambda *a, **k: {}
        for name in ("providers_brapi", "providers_awesomeapi", "providers_binance",
                     "providers_openmeteo"):
            module = getattr(server_module, name)
            self.addCleanup(setattr, module, "load", module.load)
            module.load = lambda *a, **k: []

        socket.socket.connect = guarded
        self.addCleanup(setattr, socket.socket, "connect", real_connect)

        app = App(dict(CONFIG), clock=FakeClock())
        app.quotes()
        self.assertEqual(opened, [], "a unit test reached an upstream")

    def test_every_history_provider_is_discovered(self):
        # The guard above is only as good as what it enumerates, so the
        # enumeration itself is asserted: a provider that grows a load_history
        # must show up here without anybody editing a list.
        names = {module.__name__.rsplit(".", 1)[-1] for module in history_providers()}
        self.assertIn("providers_brapi", names)
        self.assertIn("providers_awesomeapi", names)
        self.assertIn("providers_binance", names)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


CONFIG = {
    "quotes": ["PETR4"], "fx": ["USD-BRL"], "crypto": ["BTC"],
    "city": "Sao Paulo", "timezone": "America/Sao_Paulo",
    "quotes_interval_s": 300, "weather_interval_s": 900, "brapi_token": "",
    "history_interval_s": 21600, "history_days": 30,
}


class AppPayloadTests(unittest.TestCase):
    """The assembly, with every provider replaced. No network, by construction."""

    def setUp(self):
        self.clock = FakeClock()
        self.app = App(dict(CONFIG), clock=self.clock)
        self._stub_history()

    def _stub_history(self):
        """No history provider may reach the network from a unit test.

        Stubbed for every test in this class rather than per test, because the
        omission is silent: a live load_history simply fetches, the assertions
        still pass, and the only symptom is the suite getting slower. It is
        also what `unshare -n` would turn into a failure nobody could read.
        """
        for module in history_providers():
            self.addCleanup(setattr, module, "load_history", module.load_history)
            module.load_history = lambda *args, **kwargs: {}

    def _stub_providers(self, quotes=None, fx=None, crypto=None, fail=None):
        import server.server as server_module

        for name, value in (("providers_brapi", quotes), ("providers_awesomeapi", fx),
                            ("providers_binance", crypto)):
            module = getattr(server_module, name)

            def make(value=value):
                def load(*args, **kwargs):
                    if fail is not None:
                        raise UpstreamError(fail)
                    return list(value or [])
                return load

            self.addCleanup(setattr, module, "load", module.load)
            module.load = make()

    def test_quotes_payload_carries_all_three_markets_and_a_stale_flag(self):
        self._stub_providers(
            quotes=[{"symbol": "PETR4", "price": 48.5, "changePct": -0.23}],
            fx=[{"pair": "USD/BRL", "rate": 5.14, "changePct": 0.36}],
            crypto=[{"symbol": "BTC", "price": 81470.0, "changePct": 1.01}],
        )
        payload = self.app.quotes()
        self.assertEqual(set(payload), {"quotes", "fx", "crypto", "stale", "theme", "night", "language", "actions"})
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["quotes"][0]["symbol"], "PETR4")

    def test_quotes_carries_the_configured_theme(self):
        """T6.7: the theme rides /quotes, because DataPoller merges this
        response and /weather into the one payload the page gets -- a third
        endpoint would be a third request per cycle for a string a human
        changes by hand.

        A real name rather than the default, so the assertion can fail: with
        "neon" on both sides this would pass against a hard-coded literal."""
        app = App(dict(CONFIG, theme="plain"), clock=self.clock)
        self._stub_providers(quotes=[], fx=[], crypto=[])
        self.assertEqual(app.quotes()["theme"], "plain")

    def test_quotes_theme_is_empty_when_config_omits_it(self):
        """An absent key is an empty string, never a missing one: DataPayload
        drops it from the payload on empty, and the page then falls back to
        neon -- the same path a typo takes. A missing key here would make the
        Java side's optString return the default anyway, but the contract
        shape is asserted elsewhere and it must not depend on config."""
        app = App({k: v for k, v in CONFIG.items() if k != "theme"}, clock=self.clock)
        self._stub_providers(quotes=[], fx=[], crypto=[])
        self.assertEqual(app.quotes()["theme"], "")

    def test_quotes_carries_the_configured_language(self):
        """T6.11: everything a person reads comes from a key in this file, so
        a panel in another country is a restart of this server and never a
        rebuild of the APK (ADR 0013).

        A real tag rather than the default, so the assertion can fail."""
        app = App(dict(CONFIG, language="en"), clock=self.clock)
        self._stub_providers(quotes=[], fx=[], crypto=[])
        self.assertEqual(app.quotes()["language"], "en")

    def test_quotes_language_is_empty_when_config_omits_it(self):
        """An absent key is an empty string, never a missing one. The page
        reads a falsy tag as "use the panel's own language", which is the same
        path a typo takes -- and that fallback is pt-BR and not English, so a
        mistake never switches the panel to a language nobody asked for."""
        app = App({k: v for k, v in CONFIG.items() if k != "language"},
                  clock=self.clock)
        self._stub_providers(quotes=[], fx=[], crypto=[])
        self.assertEqual(app.quotes()["language"], "")

    def test_quotes_carries_the_night_window_as_the_config_spells_it(self):
        """T6.4: the window rides /quotes beside `theme`, and it rides as two
        strings rather than as a boolean.

        The panel is the thing that dims, so the comparison belongs to the
        phone's clock -- format.js for the glow, NightWindow.java for the
        backlight. A server that decided here would be answering with its own
        timezone, which is the failure this shape exists to make impossible.

        Values other than the defaults, so the assertion can fail: with
        22:00/07:00 on both sides it would pass against a hard-coded pair."""
        app = App(dict(CONFIG, night_start="23:30", night_end="05:45"),
                  clock=self.clock)
        self._stub_providers(quotes=[], fx=[], crypto=[])
        self.assertEqual(app.quotes()["night"],
                         {"start": "23:30", "end": "05:45"})

    def test_quotes_night_bounds_are_empty_when_config_omits_them(self):
        """An absent bound is an empty string, never a missing key. Both
        readers treat an unparseable bound as "not night" and leave the panel
        in its day profile, which is the right way round: a config typo costs
        the dimming, never the panel."""
        app = App({k: v for k, v in CONFIG.items()
                   if k not in ("night_start", "night_end")}, clock=self.clock)
        self._stub_providers(quotes=[], fx=[], crypto=[])
        self.assertEqual(app.quotes()["night"], {"start": "", "end": ""})

    def test_every_upstream_failing_still_returns_the_contract_shape(self):
        self._stub_providers(fail="everything down")
        payload = self.app.quotes()
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["quotes"], [])
        self.assertEqual(set(payload), {"quotes", "fx", "crypto", "stale", "theme", "night", "language", "actions"})

    def test_one_market_failing_does_not_empty_the_other_two(self):
        # Found on the desk, by changing a ticker to one that needs a token:
        # brapi answered 401, and because the three markets shared a cache the
        # panel went blank -- FX and crypto gone, with both of their upstreams
        # answering perfectly. A failure has to cost its own market and no
        # more. `stale` is still true, because something on the panel is
        # missing and the badge is how it says so.
        import server.server as server_module

        for module, rows in ((server_module.providers_awesomeapi,
                              [{"pair": "USD/BRL", "rate": 5.14, "changePct": 0.3}]),
                             (server_module.providers_binance,
                              [{"symbol": "BTC", "price": 81470.0, "changePct": 1.0}])):
            self.addCleanup(setattr, module, "load", module.load)
            module.load = (lambda rows: lambda *a, **k: list(rows))(rows)

        brapi = server_module.providers_brapi
        self.addCleanup(setattr, brapi, "load", brapi.load)

        def unauthorised(*args, **kwargs):
            raise UpstreamError("HTTP 401 from brapi: MISSING_TOKEN")

        brapi.load = unauthorised

        payload = self.app.quotes()
        self.assertEqual(payload["quotes"], [])
        self.assertEqual(len(payload["fx"]), 1, "a working market was emptied by another's failure")
        self.assertEqual(len(payload["crypto"]), 1)
        self.assertTrue(payload["stale"])

    def test_a_partial_first_market_does_not_crash_the_payload(self):
        """A configured ticker that does not resolve must cost its own row.

        `quotes()` read `key` inside the partial-market branch and assigned it
        five lines below. On the first market in the loop that made the whole
        payload raise UnboundLocalError -- a 500 on /quotes, and a blank panel,
        for one missing ticker. Found on the desk the first time a configured
        symbol did not come back, which is also the only condition that
        reaches that branch: with every ticker resolving it never ran.
        """
        app = App(dict(CONFIG, quotes=["PETR4", "TAE11"]), clock=self.clock)
        self._stub_providers(
            quotes=[{"symbol": "PETR4", "price": 1.0, "changePct": 0.0}],
            fx=[{"pair": "USD/BRL", "rate": 5.0, "changePct": 0.0}],
            crypto=[{"symbol": "BTC", "price": 1.0, "changePct": 0.0}],
        )
        with contextlib.redirect_stderr(io.StringIO()):
            payload = app.quotes()
        self.assertEqual([row["symbol"] for row in payload["quotes"]], ["PETR4"])
        self.assertEqual(len(payload["fx"]), 1, "another market paid for the missing ticker")
        self.assertEqual(len(payload["crypto"]), 1)
        self.assertTrue(payload["stale"])

    def test_a_partial_fx_market_names_the_pair_that_is_actually_missing(self):
        """The other half of the same bug, which does not raise.

        On any market after the first, `key` still held the *previous*
        market's key -- `symbol` while assembling `fx`. Every row then read as
        the empty string, so the diagnostic named every configured pair as
        missing, including the ones sitting in front of it.
        """
        app = App(dict(CONFIG, fx=["USD-BRL", "CNY-BRL"]), clock=self.clock)
        self._stub_providers(
            quotes=[{"symbol": "PETR4", "price": 1.0, "changePct": 0.0}],
            fx=[{"pair": "USD/BRL", "rate": 5.0, "changePct": 0.0}],
            crypto=[{"symbol": "BTC", "price": 1.0, "changePct": 0.0}],
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            payload = app.quotes()
        report = stderr.getvalue()
        self.assertEqual([row["pair"] for row in payload["fx"]], ["USD/BRL"])
        self.assertIn("CNY-BRL", report)
        self.assertNotIn("USD-BRL", report,
                         "the pair that did arrive was reported missing")

    def test_a_market_that_recovers_alone_clears_the_stale_flag(self):
        import server.server as server_module

        # Every configured symbol has to come back, or the payload is stale by
        # the rule below -- which is the point of that rule.
        self._stub_providers(quotes=[{"symbol": "PETR4", "price": 1.0, "changePct": 0.0}],
                             fx=[{"pair": "USD/BRL", "rate": 5.0, "changePct": 0.0}],
                             crypto=[{"symbol": "BTC", "price": 1.0, "changePct": 0.0}])
        brapi = server_module.providers_brapi
        failing = {"now": True}
        working = brapi.load

        def sometimes(*args, **kwargs):
            if failing["now"]:
                raise UpstreamError("down")
            return working(*args, **kwargs)

        brapi.load = sometimes

        self.assertTrue(self.app.quotes()["stale"])
        failing["now"] = False
        self.clock.now = 301
        self.assertFalse(self.app.quotes()["stale"])

    def test_a_cold_failure_still_returns_the_contract_shape(self):
        # The panel must be able to render the response of a server whose
        # upstreams have never answered. An empty list is renderable; a
        # missing key is a TypeError in the page.
        self._stub_providers(fail="everything down")
        payload = self.app.quotes()
        for key in ("quotes", "fx", "crypto"):
            self.assertIsInstance(payload[key], list)

    def test_incomplete_history_is_retried_soon_rather_than_cached_for_hours(self):
        # Seen on this desk: six rows got their series and SEER3 got none, and
        # because the cache held *something* the gap would have been kept for
        # the full six-hour TTL. A missing symbol is an ordinary rate limit,
        # not an outage.
        app = self.app
        long_ttl = app.config["history_interval_s"]

        app.history_caches["quotes"].value = {}
        self.assertLess(app._history_ttl("quotes"), long_ttl)

        app.history_caches["quotes"].value = {"PETR4": [1.0, 2.0]}
        self.assertEqual(app._history_ttl("quotes"), long_ttl,
                         "a complete history should keep the long TTL")

        app.config["quotes"] = ["PETR4", "SEER3"]
        self.assertLess(app._history_ttl("quotes"), long_ttl,
                        "a partial history should be retried sooner")

    def test_a_market_returning_fewer_rows_than_configured_is_stale(self):
        # With one symbol per brapi request, a 429 on one ticker returns the
        # other two and looks like a success. That row would disappear from the
        # panel for a whole TTL with no badge, and a rate-limited request is
        # not a delisted ticker.
        self._stub_providers(
            quotes=[],  # CONFIG asks for PETR4
            fx=[{"pair": "USD/BRL", "rate": 5.0, "changePct": 0.0}],
            crypto=[{"symbol": "BTC", "price": 1.0, "changePct": 0.0}],
        )
        payload = self.app.quotes()
        self.assertTrue(payload["stale"])
        # The markets that did answer keep their rows.
        self.assertEqual(len(payload["fx"]), 1)
        self.assertEqual(len(payload["crypto"]), 1)

    def test_quotes_are_cached_across_calls(self):
        calls = []
        import server.server as server_module

        # Stub the other two first: _stub_providers replaces all three, so a
        # counter installed before it would be the thing it overwrote.
        self._stub_providers(fx=[], crypto=[])
        module = server_module.providers_brapi
        self.addCleanup(setattr, module, "load", module.load)
        module.load = lambda *a, **k: (calls.append(1), [])[1]

        self.app.quotes()
        self.app.quotes()
        self.assertEqual(len(calls), 1)
        self.clock.now = 301
        self.app.quotes()
        self.assertEqual(len(calls), 2)

    def _stub_weather(self, forecast_fails=False):
        """Replace the two outbound seams and count the geocodes."""
        import server.server as server_module

        module = server_module.providers_openmeteo
        counts = {"geocode": 0, "forecast": 0}

        def fetch_geocode(city, get=None):
            counts["geocode"] += 1
            return {"results": [{"name": "São Paulo", "latitude": -23.5,
                                 "longitude": -46.6}]}

        def fetch_forecast(lat, lon, timezone, get=None):
            counts["forecast"] += 1
            if forecast_fails:
                raise UpstreamError("forecast down")
            return {"current": {"time": "2026-09-19T11:15", "temperature_2m": 24.0,
                                "weather_code": 2},
                    "daily": {"time": ["2026-09-19"], "temperature_2m_max": [26.1],
                              "temperature_2m_min": [15.5]}}

        for name, stub in (("fetch_geocode", fetch_geocode),
                           ("fetch_forecast", fetch_forecast)):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, stub)
        return counts

    def test_weather_geocode_happens_once_and_is_reused(self):
        counts = self._stub_weather()

        payload = self.app.weather()
        self.clock.now = 10000
        self.app.weather()

        self.assertEqual(counts["geocode"], 1, "a city that has not moved was located twice")
        self.assertEqual(counts["forecast"], 2)
        self.assertEqual(payload["city"], "São Paulo")
        self.assertFalse(payload["stale"])

    def test_a_forecast_outage_does_not_throw_away_the_coordinates(self):
        # Geocoding and forecasting used to be one call, so a forecast failure
        # discarded coordinates that had just been resolved -- and every later
        # refresh re-geocoded, doubling the requests against a 10k/day budget
        # exactly while the provider was already struggling.
        counts = self._stub_weather(forecast_fails=True)

        for tick in (0, 10000, 20000):
            self.clock.now = tick
            payload = self.app.weather()
            self.assertTrue(payload["stale"])

        self.assertEqual(counts["geocode"], 1, "the city was re-located after a forecast failure")
        self.assertEqual(counts["forecast"], 3)


class ActionIdTests(unittest.TestCase):
    """Path matching for the one route that changes this machine.

    Narrow on purpose and asserted here rather than left to the catalogue:
    ADR 0015's promise is that nothing from the request is ever interpolated,
    and an allowlist of characters in front of an allowlist of names is how
    that promise stops depending on the lookup being written correctly."""

    def test_a_single_segment_matches(self):
        self.assertEqual(action_id("/action/mute-audio"), "mute-audio")

    def test_nesting_traversal_and_emptiness_do_not_match(self):
        for path in ("/action/", "/action", "/action/a/b", "/action/../etc",
                     "/actions/x", "/Action/x"):
            self.assertIsNone(action_id(path), path)

    def test_a_shell_metacharacter_is_not_an_id(self):
        # None of these can reach the catalogue, so none of them can reach a
        # command even if the catalogue were one day written carelessly.
        for rest in ("mute;rm", "mute&&rm", "mute rm", "mute\nrm", "mute|rm",
                     "mute$(rm)", "mute`rm`", "mute%2Frm", "../etc/passwd",
                     "MUTE-AUDIO", "-mute", "mute_audio", "mute.audio"):
            self.assertIsNone(action_id("/action/" + rest), rest)

    def test_a_trailing_newline_is_not_part_of_an_id(self):
        # Python's `$` matches before a trailing newline as well as at the
        # end, so `^[a-z0-9-]*$` accepts this one. `fullmatch` does not.
        self.assertIsNone(action_id("/action/mute-audio\n"))

    def test_post_to_an_unknown_action_is_404_without_an_app(self):
        # No app is 503, like every other route that needs config.
        status, _, content_type, _ = route("POST", "/action/mute-audio")
        self.assertEqual(status, 503)
        self.assertEqual(content_type, "application/json")

    def test_get_to_an_action_is_404(self):
        status, _, _, _ = route("GET", "/action/mute-audio")
        self.assertEqual(status, 404)


class RouteWithoutAppTests(unittest.TestCase):
    """The data routes without state, which is what keeps the older
    two-argument route tests meaningful."""

    def test_quotes_without_an_app_is_503_not_a_crash(self):
        status, _, content_type, _ = route("GET", "/quotes")
        self.assertEqual(status, 503)
        self.assertEqual(content_type, "application/json")

    def test_weather_without_an_app_is_503(self):
        status, _, _, _ = route("GET", "/weather")
        self.assertEqual(status, 503)


if __name__ == "__main__":
    unittest.main()


class MoonOffTheRequestPathTests(unittest.TestCase):
    """T6.15's review: the moon may never block or fail a payload.

    `weather()` is served synchronously. `upstream.TIMEOUT_S` is 10s,
    `DataPoller.TIMEOUT_MS` is 5s, and `DataPayload.merge` returns null if
    either body fails -- so a slow USNO would have dropped the whole payload
    for that cycle, quotes and fx and crypto and an already-fresh weather with
    it, to fetch the least important thing on the panel.
    """

    def setUp(self):
        self.clock = FakeClock()
        self.app = App(dict(CONFIG), clock=self.clock)
        self.calls = []

        def never_finishes(when=None, get=None):
            self.calls.append(when)
            raise AssertionError("the moon was fetched on the request path")

        self.addCleanup(setattr, providers_usno, "moon_phase",
                        providers_usno.moon_phase)
        providers_usno.moon_phase = never_finishes
        # The forecast is stubbed too: this class is about the moon, and a live
        # geocode would be the same fault in a different provider.
        self.addCleanup(setattr, providers_openmeteo, "fetch_geocode",
                        providers_openmeteo.fetch_geocode)
        self.addCleanup(setattr, providers_openmeteo, "fetch_forecast",
                        providers_openmeteo.fetch_forecast)
        providers_openmeteo.fetch_geocode = lambda city: {
            "results": [{"name": city, "latitude": 0.0, "longitude": 0.0,
                         "timezone": "UTC"}]}
        providers_openmeteo.fetch_forecast = lambda *a, **k: {
            "current": {"time": "2026-09-22T00:00", "temperature_2m": 21.0,
                        "weather_code": 2, "is_day": 0},
            "daily": {"time": ["2026-09-22"], "temperature_2m_max": [26.0],
                      "temperature_2m_min": [15.0],
                      "precipitation_probability_max": [98]}}

    def test_the_payload_still_carries_a_moon_when_the_fetch_cannot_answer(self):
        # `moon_phase` raising is the whole point of the change the review
        # asked for -- it is what lets TimedCache record a failure and retry --
        # so the card has to draw from the fallback at the call site rather
        # than lose the key.
        weather = self.app.weather()
        self.assertIn("moon", weather)
        self.assertEqual(weather["moon"]["source"], "mean")
        self.assertIn(weather["moon"]["phase"], providers_usno.PHASE_NAMES)

    def test_the_rest_of_the_card_is_untouched_by_the_moon_failing(self):
        weather = self.app.weather()
        self.assertEqual(weather["tempC"], 21.0)
        self.assertEqual(weather["precipProb"], 98)
        self.assertIs(weather["isDay"], False)
        self.assertFalse(weather["stale"])

    def test_the_fetch_is_not_awaited_by_the_caller(self):
        # The background thread may or may not have run by the time this
        # returns -- what matters is that `weather()` came back at all. The
        # stub raises AssertionError, so if the refresh were awaited on this
        # thread the call above would have propagated it.
        self.app.weather()
        self.app.weather()
