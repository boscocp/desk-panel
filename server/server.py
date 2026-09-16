#!/usr/bin/env python3
"""Desk panel PC server.

Standard library only -- see server/CLAUDE.md. This process is the login
signal (invariant 2 in the root CLAUDE.md): it is meant to be launched by a
logged-in user's session and to die with it, never to auto-restart or run as
a service.

The request handler only routes and serialises. All real logic lives in
plain functions (`route`, below, and whatever T3.2+ adds) so tests can call
them directly without a socket -- see server/CLAUDE.md and TT.2.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "0.0.0.0"
PORT = 8777


def route(method, path):
    """Pure routing: (method, path) -> (status, body_bytes, content_type).

    No side effects, no I/O -- callable directly from tests without
    starting a server.
    """
    if method == "GET" and path == "/ping":
        body = json.dumps({"ok": True}).encode("utf-8")
        return 200, body, "application/json"
    return 404, b"", "text/plain"


class Handler(BaseHTTPRequestHandler):
    """Dumb by design: routes to `route()` and serialises its result."""

    def _handle(self, method):
        status, body, content_type = route(method, self.path)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def main():
    server = HTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
