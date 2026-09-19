"""HTTP integration tests -- the real socket layer, not route() in isolation.

TT.2 already covers route()'s logic directly (no socket); these tests exist
only to prove the wiring around it: that Handler actually serialises route()'s
return value into a real status line, real headers, and real body bytes over
a real TCP connection.

Binds on port 0 so the OS assigns a free port -- see server/CLAUDE.md and the
TT.3 task file. A hard-coded port fails on a busy machine or when the real
server (T3.9 installs one on this box) is already listening.

`/quotes` and `POST /action/x` were left out when this file was written,
because T3.3 and T3.7 had not landed and there was nothing to hit. Both landed
in wave 8 and are covered below.

Still no network: the second server class replaces the provider modules'
`load` functions, so the payload comes from this file and `upstream.py` is
never reached -- see server/CLAUDE.md.
"""
import http.client
import json
import threading
import unittest
from functools import partial

from server import providers_awesomeapi, providers_binance, providers_brapi
from server.server import App, Handler, Server


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def _get(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            return resp, body
        finally:
            conn.close()

    def test_ping_over_real_http(self):
        resp, body = self._get("/ping")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        self.assertEqual(resp.getheader("Content-Length"), str(len(body)))
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})

    def test_unknown_path_over_real_http(self):
        resp, body = self._get("/nonexistent")
        self.assertEqual(resp.status, 404)
        self.assertEqual(resp.getheader("Content-Type"), "text/plain")
        self.assertEqual(body, b"")


QUOTES = [{"symbol": "PETR4", "price": 48.5, "changePct": -0.23}]
FX = [{"pair": "USD/BRL", "rate": 5.1434, "changePct": 0.36882}]
CRYPTO = [{"symbol": "BTC", "price": 81470.0, "changePct": 1.016}]


class DataRouteTests(unittest.TestCase):
    """The routes that need an App behind them, over a real socket.

    A separate server from the class above, built with functools.partial so
    the app is this server's state rather than a class attribute every other
    server in the process would share.
    """

    @classmethod
    def setUpClass(cls):
        cls._restore = []
        for module, value in ((providers_brapi, QUOTES),
                              (providers_awesomeapi, FX),
                              (providers_binance, CRYPTO)):
            cls._restore.append((module, module.load))
            module.load = (lambda value: lambda *a, **k: list(value))(value)

        config = {"quotes": ["PETR4"], "fx": ["USD-BRL"], "crypto": ["BTC"],
                  "quotes_interval_s": 300, "weather_interval_s": 900,
                  "city": "Sao Paulo", "timezone": "America/Sao_Paulo",
                  "brapi_token": ""}
        cls.server = Server(("127.0.0.1", 0), partial(Handler, app=App(config)))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        for module, original in cls._restore:
            module.load = original

    def _request(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            return resp, resp.read()
        finally:
            conn.close()

    def test_quotes_returns_the_t1_2_contract_shape(self):
        resp, body = self._request("/quotes")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        self.assertEqual(resp.getheader("Content-Length"), str(len(body)))

        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(set(payload), {"quotes", "fx", "crypto", "stale"})
        self.assertEqual(payload["quotes"][0]["symbol"], "PETR4")
        self.assertEqual(set(payload["quotes"][0]), {"symbol", "price", "changePct"})
        self.assertEqual(set(payload["fx"][0]), {"pair", "rate", "changePct"})
        self.assertEqual(set(payload["crypto"][0]), {"symbol", "price", "changePct"})
        self.assertFalse(payload["stale"])

    def test_quotes_is_valid_utf8_json_over_the_wire(self):
        # Content-Length is in bytes and the payload can carry non-ASCII (a
        # city name does). A length computed on characters would truncate the
        # body and the client would hang or fail to parse.
        resp, body = self._request("/quotes")
        self.assertEqual(int(resp.getheader("Content-Length")), len(body))
        json.loads(body.decode("utf-8"))

    def test_post_to_an_action_returns_501(self):
        resp, body = self._request("/action/x", method="POST")
        self.assertEqual(resp.status, 501)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")), {"error": "not implemented"})

    def test_get_to_an_action_is_still_404(self):
        resp, _ = self._request("/action/x")
        self.assertEqual(resp.status, 404)

    def test_ping_still_works_on_a_server_that_has_an_app(self):
        resp, body = self._request("/ping")
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})


if __name__ == "__main__":
    unittest.main()
