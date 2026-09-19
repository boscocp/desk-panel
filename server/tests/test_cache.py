"""TT.2 -- the cache, the stale fallback, and the payloads built on them.

No network, no sleeping. `TimedCache` takes `now` as an argument and `App`
takes its clock, so an hour passes here in a function call. A test that
slept for a 300s TTL would be a test nobody runs.

What is actually being pinned is a product decision from T3.3 step 5: an
upstream that has gone away must cost the panel its freshness, never its
contents. The panel showing a slightly old price beats the panel showing
nothing, and `stale` is how the page knows to say so.
"""
import unittest

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

    def test_only_upstream_errors_are_swallowed(self):
        # A bug in a normaliser must not be laundered into "stale". Anything
        # that is not an UpstreamError is a defect in this repository, and it
        # should reach the log as a traceback.
        cache = TimedCache()

        def bug():
            raise ZeroDivisionError("a real bug")

        with self.assertRaises(ZeroDivisionError):
            cache.get(0, 300, bug)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


CONFIG = {
    "quotes": ["PETR4"], "fx": ["USD-BRL"], "crypto": ["BTC"],
    "city": "Sao Paulo", "timezone": "America/Sao_Paulo",
    "quotes_interval_s": 300, "weather_interval_s": 900, "brapi_token": "",
}


class AppPayloadTests(unittest.TestCase):
    """The assembly, with every provider replaced. No network, by construction."""

    def setUp(self):
        self.clock = FakeClock()
        self.app = App(dict(CONFIG), clock=self.clock)

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
        self.assertEqual(set(payload), {"quotes", "fx", "crypto", "stale"})
        self.assertFalse(payload["stale"])
        self.assertEqual(payload["quotes"][0]["symbol"], "PETR4")

    def test_one_upstream_failing_marks_the_whole_payload_stale(self):
        # One cache for three markets, so a partial failure is reported as
        # what it is: something on this panel is older than it looks.
        self._stub_providers(fail="brapi down")
        payload = self.app.quotes()
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["quotes"], [])
        self.assertEqual(set(payload), {"quotes", "fx", "crypto", "stale"})

    def test_a_cold_failure_still_returns_the_contract_shape(self):
        # The panel must be able to render the response of a server whose
        # upstreams have never answered. An empty list is renderable; a
        # missing key is a TypeError in the page.
        self._stub_providers(fail="everything down")
        payload = self.app.quotes()
        for key in ("quotes", "fx", "crypto"):
            self.assertIsInstance(payload[key], list)

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

    def test_weather_geocode_happens_once_and_is_reused(self):
        import server.server as server_module

        module = server_module.providers_openmeteo
        seen = []

        def load(city, timezone, coords=None, get=None):
            seen.append(coords)
            return ({"tempC": 24.0, "minC": 15.5, "maxC": 26.1, "code": 2,
                     "city": "São Paulo"},
                    {"lat": -23.5, "lon": -46.6, "city": "São Paulo"})

        self.addCleanup(setattr, module, "load", module.load)
        module.load = load

        self.app.weather()
        self.clock.now = 1000
        payload = self.app.weather()

        self.assertIsNone(seen[0], "the first call should have no cached coordinates")
        self.assertIsNotNone(seen[1], "the second call should reuse them")
        self.assertEqual(payload["city"], "São Paulo")
        self.assertFalse(payload["stale"])


class ActionIdTests(unittest.TestCase):
    """The v2 placeholder's path matching. Narrow on purpose: when this is
    implemented it takes a closed allowlist from config, and the first half of
    that promise is refusing to match anything shaped like a path."""

    def test_a_single_segment_matches(self):
        self.assertEqual(action_id("/action/lock"), "lock")

    def test_nesting_traversal_and_emptiness_do_not_match(self):
        for path in ("/action/", "/action", "/action/a/b", "/action/../etc",
                     "/actions/x", "/Action/x"):
            self.assertIsNone(action_id(path), path)

    def test_post_to_an_action_is_501_not_404(self):
        # 501 says "this route exists and does nothing yet", which is the
        # truth. 404 would say it does not exist and 200 would say something
        # happened.
        status, _, content_type = route("POST", "/action/lock")
        self.assertEqual(status, 501)
        self.assertEqual(content_type, "application/json")

    def test_get_to_an_action_is_404(self):
        status, _, _ = route("GET", "/action/lock")
        self.assertEqual(status, 404)


class RouteWithoutAppTests(unittest.TestCase):
    """The data routes without state, which is what keeps the older
    two-argument route tests meaningful."""

    def test_quotes_without_an_app_is_503_not_a_crash(self):
        status, _, content_type = route("GET", "/quotes")
        self.assertEqual(status, 503)
        self.assertEqual(content_type, "application/json")

    def test_weather_without_an_app_is_503(self):
        status, _, _ = route("GET", "/weather")
        self.assertEqual(status, 503)


if __name__ == "__main__":
    unittest.main()
