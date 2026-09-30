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
import os
import tempfile
import threading
import types
import unittest
from functools import partial
from pathlib import Path
from unittest import mock

from server import providers_awesomeapi, providers_binance, providers_brapi
from server import server as server_module
from server.server import APK_CONTENT_TYPE, App, Handler, Server



# An app with nothing in it but the one switch /app reads.
APK_ON = types.SimpleNamespace(config={"serve_apk": True})

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
            cls._restore.append((module, "load", module.load))
            module.load = (lambda value: lambda *a, **k: list(value))(value)

        # load_history as well, and the omission was not theoretical: leaving
        # it live made this suite fetch thirty daily closes from two real
        # upstreams, which is exactly what server/CLAUDE.md forbids. It showed
        # up as the runtime tripling, and nothing else.
        # Every provider with a load_history, and the list is the thing that
        # goes stale: brapi gained one after this was written and promptly
        # reached the network, which the assertion below caught only because
        # it pins the exact series. A new provider must be added here too.
        for module, series in ((providers_awesomeapi, {"USD/BRL": [5.1, 5.2, 5.14]}),
                               (providers_binance, {"BTC": [80000.0, 81000.0, 81470.0]}),
                               (providers_brapi, {"PETR4": [48.0, 48.2, 48.5]})):
            cls._restore.append((module, "load_history", module.load_history))
            module.load_history = (lambda series: lambda *a, **k: dict(series))(series)

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
        for module, name, original in cls._restore:
            setattr(module, name, original)

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
        self.assertEqual(set(payload), {"quotes", "fx", "crypto", "stale", "theme", "night",
                                        "language", "actions", "agenda", "b3Open", "volume"})
        self.assertEqual(payload["quotes"][0]["symbol"], "PETR4")
        self.assertEqual(set(payload["quotes"][0]), {"symbol", "price", "changePct", "history"})
        self.assertEqual(set(payload["fx"][0]), {"pair", "rate", "changePct", "history"})
        self.assertEqual(set(payload["crypto"][0]), {"symbol", "price", "changePct", "history"})

    def test_a_row_carries_its_own_series_and_an_unmatched_one_carries_none(self):
        payload = json.loads(self._request("/quotes")[1].decode("utf-8"))
        # Each row gets the series its own symbol was stubbed with, and no
        # other row's.
        self.assertEqual(payload["fx"][0]["history"], [5.1, 5.2, 5.14])
        self.assertEqual(payload["crypto"][0]["history"], [80000.0, 81000.0, 81470.0])
        self.assertEqual(payload["quotes"][0]["history"], [48.0, 48.2, 48.5])
        self.assertFalse(payload["stale"])

    def test_quotes_is_valid_utf8_json_over_the_wire(self):
        # Content-Length is in bytes and the payload can carry non-ASCII (a
        # city name does). A length computed on characters would truncate the
        # body and the client would hang or fail to parse.
        resp, body = self._request("/quotes")
        self.assertEqual(int(resp.getheader("Content-Length")), len(body))
        json.loads(body.decode("utf-8"))

    def test_post_to_an_action_nobody_enabled_returns_404(self):
        # The fixture app enables nothing, which is the default. 404 and not
        # 501: an action that is not enabled does not exist as far as an
        # unauthenticated caller is concerned (ADR 0015).
        resp, body = self._request("/action/mute-audio", method="POST")
        self.assertEqual(resp.status, 404)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")), {"error": "unknown action"})

    def test_get_to_an_action_is_still_404(self):
        resp, _ = self._request("/action/mute-audio")
        self.assertEqual(resp.status, 404)

    def test_ping_still_works_on_a_server_that_has_an_app(self):
        resp, body = self._request("/ping")
        self.assertEqual(resp.status, 200)
        # "unknown": this App was given no display reader (T4.6), and unknown
        # is what leaves the phone following the login alone.
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True, "display": "unknown"})



class ApkOverRealHttpTests(unittest.TestCase):
    """T3.6 over a socket. route()'s own tests cover which file is chosen;
    what can only be seen here is the serialisation -- a HEAD that reports the
    length of a body it does not send, and an extra header actually reaching
    the wire."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.tmp.name)
        cls.payload = b"PK\x03\x04" + b"apk-bytes" * 100
        apk = cls.directory / "desk-panel-release.apk"
        apk.write_bytes(cls.payload)
        os.utime(apk, (1_000, 1_000))
        # The route reads a module constant, because where the build output
        # lands is a property of the checkout rather than of the panel.
        cls.patch = mock.patch.object(server_module, "APK_DIR", cls.directory)
        cls.patch.start()

        # serve_apk on: /app is off by default since T9.4 (ADR 0018), and
        # these tests are about what it serves when the owner turns it on.
        # serve_apk on: /app is off by default since T9.4 (ADR 0018), and
        # these tests are about what it serves when the owner turns it on.
        cls.server = Server(("127.0.0.1", 0), partial(Handler, app=APK_ON))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.patch.stop()
        cls.tmp.cleanup()

    def _request(self, path, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            return resp, body
        finally:
            conn.close()

    def test_get_app_returns_the_apk_bytes(self):
        resp, body = self._request("/app")
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, self.payload)
        self.assertEqual(resp.getheader("Content-Type"), APK_CONTENT_TYPE)
        self.assertEqual(
            resp.getheader("Content-Disposition"),
            'attachment; filename="desk-panel-release.apk"',
        )

    def test_head_app_sends_the_length_and_no_body(self):
        # This is the whole reason the acceptance uses HEAD: it asserts the
        # type without moving two megabytes. A HEAD that reported
        # Content-Length: 0 would make the assertion meaningless.
        resp, body = self._request("/app", method="HEAD")
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(resp.getheader("Content-Length"), str(len(self.payload)))
        self.assertEqual(resp.getheader("Content-Type"), APK_CONTENT_TYPE)

    def test_head_works_on_the_json_routes_too(self):
        # do_HEAD routes as GET, so every route answers it. A 501 here would
        # be the http.server default for an undefined method.
        resp, body = self._request("/ping", method="HEAD")
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, b"")
        # The stub app has no display reader, so the body says "unknown".
        self.assertEqual(resp.getheader("Content-Length"),
                         str(len(b'{"ok": true, "display": "unknown"}')))

    def test_index_is_html_and_links_to_app(self):
        resp, body = self._request("/")
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader("Content-Type").startswith("text/html"))
        self.assertIn(b'href="/app"', body)


class ApkMissingOverRealHttpTests(unittest.TestCase):
    """The same server against an empty out/, which is what a fresh clone has."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patch = mock.patch.object(server_module, "APK_DIR", Path(cls.tmp.name))
        cls.patch.start()
        # serve_apk on: /app is off by default since T9.4 (ADR 0018), and
        # these tests are about what it serves when the owner turns it on.
        # serve_apk on: /app is off by default since T9.4 (ADR 0018), and
        # these tests are about what it serves when the owner turns it on.
        cls.server = Server(("127.0.0.1", 0), partial(Handler, app=APK_ON))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.patch.stop()
        cls.tmp.cleanup()

    def test_app_is_404_with_the_build_command_in_it(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/app")
            resp = conn.getresponse()
            body = resp.read()
        finally:
            conn.close()
        self.assertEqual(resp.status, 404)
        self.assertIn(b"assembleRelease", body)

if __name__ == "__main__":
    unittest.main()
