"""Unit tests for server.route -- pure routing, no socket, no network.

route() is what the request handler defers to entirely (server/CLAUDE.md:
"keep the request handler dumb"), so every reachable (method, path) pair
belongs here rather than behind a live HTTPServer.
"""
import json
import unittest

from server.server import route


class RouteTests(unittest.TestCase):
    def test_get_ping_returns_200_ok_json(self):
        status, body, content_type = route("GET", "/ping")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")), {"ok": True})

    def test_unknown_path_returns_404(self):
        status, body, content_type = route("GET", "/nope")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(content_type, "text/plain")

    def test_post_to_ping_returns_404(self):
        # /ping is documented and tested as a GET-only route; POST must not
        # silently match it.
        status, body, content_type = route("POST", "/ping")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")
        self.assertEqual(content_type, "text/plain")

    def test_path_is_case_and_slash_sensitive(self):
        status, _, _ = route("GET", "/ping/")
        self.assertEqual(status, 404)
        status, _, _ = route("GET", "/Ping")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
