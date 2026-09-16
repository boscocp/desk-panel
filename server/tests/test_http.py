"""HTTP integration tests -- the real socket layer, not route() in isolation.

TT.2 already covers route()'s logic directly (no socket); these tests exist
only to prove the wiring around it: that Handler actually serialises route()'s
return value into a real status line, real headers, and real body bytes over
a real TCP connection.

Binds on port 0 so the OS assigns a free port -- see server/CLAUDE.md and the
TT.3 task file. A hard-coded port fails on a busy machine or when the real
server (T3.9 installs one on this box) is already listening.

NOT covered here yet, and left out deliberately rather than faked:

- `/quotes` (TT.3 step 5) -- there is no `/quotes` route. T3.3 ("`/quotes`
  proxy"), which is supposed to add it, is still `todo` in tasks/STATUS.md.
- `POST /action/x` returning 501 (TT.3 step 6) -- route() has no `/action/*`
  branch yet either; today it falls through to plain 404. T3.7 ("`POST
  /action/{id}` stub returning 501"), which is supposed to add that branch,
  is also still `todo`.

Add both once T3.3 and T3.7 land -- see the TT.3 row in tasks/STATUS.md.
"""
import http.client
import json
import threading
import unittest

from server.server import Handler, Server


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


if __name__ == "__main__":
    unittest.main()
