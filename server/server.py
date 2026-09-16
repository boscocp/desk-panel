#!/usr/bin/env python3
"""Desk panel PC server.

Standard library only -- see server/CLAUDE.md. This process is the login
signal (invariant 2 in the root CLAUDE.md): it is meant to be launched by a
logged-in user's session and to die with it, never to auto-restart or run as
a service.

The request handler only routes and serialises. All real logic lives in
plain functions (`route`, `load_config`, below, and whatever T3.3+ adds) so
tests can call them directly without a socket -- see server/CLAUDE.md and
TT.2.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8777

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent / "config.example.json"

# Every key config.example.json ships, with a safe empty/inert default.
# `load_config` fills in whatever a real config.json omits so that a
# partial file degrades gracefully instead of raising KeyError deep inside
# a handler -- see server/CLAUDE.md ("config drives behaviour").
DEFAULT_CONFIG = {
    "port": PORT,
    "brapi_token": "",
    "quotes": [],
    "crypto": [],
    "fx": [],
    "city": "Sao Paulo",
    "timezone": "America/Sao_Paulo",
    "quotes_interval_s": 300,
    "weather_interval_s": 900,
    "night_start": "22:00",
    "night_end": "07:00",
    "actions": {},
}


class ConfigError(Exception):
    """A missing or malformed config.json.

    The message is always safe to print or log: it never contains the
    token or any other config value, only the path involved -- see
    server/CLAUDE.md ("secrets stay here").
    """


def load_config(path):
    """Pure: load config.json from `path`, filling missing keys with
    DEFAULT_CONFIG. Raises ConfigError -- never a bare exception -- for a
    missing file or invalid JSON, so callers get one exception type to
    handle. No I/O beyond the single read; no logging, no defaults baked
    into the network layer. Pure so TT.2 can test it without a server.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"{path} not found. Copy {EXAMPLE_CONFIG_PATH} to that path "
            f"and fill in your brapi token."
        ) from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from None

    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")

    config = dict(DEFAULT_CONFIG)
    config.update(data)
    return config


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
    # A server that starts with silently-empty config looks healthy and
    # shows an empty panel -- worse than one that refuses to start with a
    # clear message. So this is fatal, not a fallback to DEFAULT_CONFIG.
    try:
        config = load_config(CONFIG_PATH)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    port = config.get("port", PORT)
    server = HTTPServer((HOST, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
