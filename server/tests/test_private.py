"""T9.4: nobody else on the Wi-Fi reads the panel (ADR 0018).

Three behaviours the task file requires to be pinned here:

- a data route without the key answers 401, and a wrong key answers 401
  through a comparison whose time does not depend on the key;
- `/app` answers 404 unless `serve_apk = true`;
- (design 2's tamper test does not apply: design 1 shipped.)

Plus one real TLS round trip, which needs `openssl` to make a certificate and
is skipped where there is none. No private key is committed for it:
scripts/check_secrets.py refuses one, and it is right to.
"""
import hashlib
import http.client
import json
import os
import shutil
import ssl
import tempfile
import threading
import types
import unittest
from functools import partial
from pathlib import Path
from unittest import mock

from server import make_cert, private
from server.server import DEFAULT_CONFIG, Handler, TlsHandler, TlsServer, route

KEY = "k" * 43
HOST = {"Host": "192.168.1.100:8777"}


def _config(**overrides):
    config = dict(DEFAULT_CONFIG)
    config.update(overrides)
    return config


def _private_config(**overrides):
    return _config(**dict({"panel_key": KEY, "tls_cert": "cert.pem", "tls_key": "key.pem"},
                          **overrides))


class _App:
    """Just enough App for route(): config, and data that says who answered."""

    def __init__(self, config):
        self.config = config
        self.enabled_actions = []

    def quotes(self):
        return {"agenda": {"events": [{"title": "a secret meeting"}]}}

    def weather(self):
        return {"temp": 21}


class SettingsTests(unittest.TestCase):
    def test_none_of_the_three_is_open(self):
        self.assertIsNone(private.settings(_config()))

    def test_all_three_is_private_on_the_tls_port(self):
        self.assertEqual(private.settings(_private_config()),
                         (KEY, "cert.pem", "key.pem", 8778))

    def test_any_two_without_the_third_is_refused(self):
        for missing in ("panel_key", "tls_cert", "tls_key"):
            config = _private_config()
            config[missing] = ""
            with self.assertRaises(ValueError) as caught:
                private.settings(config)
            self.assertIn(missing, str(caught.exception))

    def test_a_short_key_is_refused(self):
        with self.assertRaises(ValueError):
            private.settings(_private_config(panel_key="hunter2"))

    def test_the_tls_port_cannot_be_the_plain_one(self):
        with self.assertRaises(ValueError):
            private.settings(_private_config(tls_port=8777, port=8777))
        with self.assertRaises(ValueError):
            private.settings(_private_config(tls_port="8778"))

    def test_the_default_is_open_and_apk_off(self):
        self.assertEqual(DEFAULT_CONFIG["panel_key"], "")
        self.assertIs(DEFAULT_CONFIG["serve_apk"], False)


class KeyTests(unittest.TestCase):
    def test_right_wrong_and_missing(self):
        self.assertTrue(private.key_matches(KEY, KEY))
        self.assertFalse(private.key_matches(KEY, KEY[:-1]))
        self.assertFalse(private.key_matches(KEY, None))
        self.assertFalse(private.key_matches(KEY, ""))

    def test_the_comparison_is_constant_time_over_equal_lengths(self):
        # compare_digest is constant-time only for inputs of equal length, so
        # both sides must reach it as SHA-256 digests whatever was sent.
        seen = []
        real = private.hmac.compare_digest

        def spy(a, b):
            seen.append((len(a), len(b)))
            return real(a, b)

        with mock.patch.object(private.hmac, "compare_digest", side_effect=spy):
            private.key_matches(KEY, "x")
            private.key_matches(KEY, "x" * 500)
            private.key_matches(KEY, None)
        self.assertEqual(seen, [(32, 32)] * 3)
        self.assertEqual(len(hashlib.sha256(b"").digest()), 32)


class RouteTests(unittest.TestCase):
    def _get(self, path, config, headers=None, channel="plain"):
        headers = dict(HOST, **(headers or {}))
        return route("GET", path, _App(config), headers, channel)

    def test_open_is_as_before(self):
        status, body, _, _ = self._get("/quotes", _config())
        self.assertEqual(status, 200)
        self.assertIn(b"a secret meeting", body)

    def test_private_without_the_key_is_401_and_says_nothing(self):
        for channel in ("plain", "tls"):
            status, body, _, _ = self._get("/quotes", _private_config(), channel=channel)
            self.assertEqual(status, 401)
            self.assertEqual(json.loads(body), {"error": "unauthorized"})

    def test_a_wrong_key_is_401(self):
        status, _, _, _ = self._get("/quotes", _private_config(),
                                    {"X-Panel-Key": "k" * 42 + "j"}, "tls")
        self.assertEqual(status, 401)

    def test_the_right_key_on_tls_answers(self):
        for path in ("/quotes", "/weather"):
            status, _, _, _ = self._get(path, _private_config(), {"X-Panel-Key": KEY}, "tls")
            self.assertEqual(status, 200, path)

    def test_the_right_key_on_the_plain_port_is_still_refused(self):
        # It has already crossed the air in clear; answering would teach the
        # owner that it works.
        status, _, _, _ = self._get("/quotes", _private_config(), {"X-Panel-Key": KEY}, "plain")
        self.assertEqual(status, 401)

    def test_a_press_needs_the_key_too(self):
        status, _, _, _ = route("POST", "/action/mute-audio", _App(_private_config()),
                                dict(HOST), "tls")
        self.assertEqual(status, 401)

    def test_ping_never_needs_the_key(self):
        for channel in ("plain", "tls"):
            status, _, _, _ = self._get("/ping", _private_config(), channel=channel)
            self.assertEqual(status, 200)

    def test_app_is_404_unless_serve_apk(self):
        for config, app in ((_config(), True), (_private_config(), True), (None, False)):
            status, body, _, _ = route("GET", "/app", _App(config) if app else None, dict(HOST))
            self.assertEqual(status, 404)
            self.assertEqual(body, b"")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "desk-panel-release.apk").write_bytes(b"PK\x03\x04")
            with mock.patch("server.server.APK_DIR", Path(tmp)):
                status, _, _, _ = route("GET", "/app", _App(_config(serve_apk=True)), dict(HOST))
        self.assertEqual(status, 200)

    def test_the_index_says_why_there_is_no_link(self):
        _, body, _, _ = route("GET", "/", _App(_config()), dict(HOST))
        self.assertNotIn(b'href="/app"', body)
        self.assertIn(b"serve_apk", body)


class MakeCertTests(unittest.TestCase):
    def test_the_curve_is_named_so_android_accepts_it(self):
        # The measured failure: LibreSSL wrote explicit curve parameters and
        # the Redmi's BoringSSL answered decode_error to every handshake.
        argv = make_cert.openssl_argv("openssl", "192.168.1.100", "c.pem", "k.pem")
        self.assertIn("ec_param_enc:named_curve", argv)
        self.assertIn("subjectAltName=IP:192.168.1.100", argv)
        self.assertIn("basicConstraints=critical,CA:FALSE", argv)

    def test_a_key_is_long_enough_for_the_server(self):
        self.assertGreaterEqual(len(make_cert.new_key()), private.MIN_KEY_LENGTH)
        self.assertNotEqual(make_cert.new_key(), make_cert.new_key())


@unittest.skipIf(shutil.which("openssl") is None, "no openssl to make a certificate with")
class TlsRoundTripTests(unittest.TestCase):
    """The real listener, a real certificate, a client that pins it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cert, key = make_cert.make("127.0.0.1", Path(cls.tmp.name), shutil.which("openssl"))
        cls.cert = str(cert)
        config = _config(panel_key=KEY, tls_cert=str(cert), tls_key=str(key))
        app = types.SimpleNamespace(config=config, quotes=lambda: {"q": 1},
                                    weather=lambda: {"w": 1}, display=None)
        cls.server = TlsServer(("127.0.0.1", 0), partial(TlsHandler, app=app, channel="tls"),
                               private.context(str(cert), str(key)))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def _get(self, path, headers=None):
        ctx = ssl.create_default_context(cafile=self.cert)
        conn = http.client.HTTPSConnection("127.0.0.1", self.port, context=ctx, timeout=5)
        try:
            conn.request("GET", path, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            conn.close()

    def test_the_key_over_tls_answers(self):
        self.assertEqual(self._get("/quotes", {"X-Panel-Key": KEY}), (200, b'{"q": 1}'))

    def test_no_key_over_tls_is_401(self):
        self.assertEqual(self._get("/quotes")[0], 401)

    def test_a_client_that_does_not_pin_the_certificate_is_refused(self):
        conn = http.client.HTTPSConnection("127.0.0.1", self.port,
                                           context=ssl.create_default_context(), timeout=5)
        with self.assertRaises(ssl.SSLError):
            conn.request("GET", "/ping")
        conn.close()

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_the_key_file_is_private(self):
        key = Path(self.tmp.name) / "127.0.0.1.key"
        self.assertEqual(key.stat().st_mode & 0o077, 0)


class PlainHandlerIsUnchangedTests(unittest.TestCase):
    def test_the_plain_handler_defaults_to_the_plain_channel(self):
        self.assertEqual(Handler.__init__.__kwdefaults__["channel"], "plain")


if __name__ == "__main__":
    unittest.main()
