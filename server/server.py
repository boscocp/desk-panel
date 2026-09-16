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
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8777
MIN_PYTHON = (3, 11)

SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLE_CONFIG_PATH = SCRIPT_DIR / "config.example.json"

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


def config_search_paths(argv, env, script_dir):
    """Pure: ordered config path candidates, highest priority first.

    Order: `--config <path>` (from argv), then `DESK_PANEL_CONFIG` (from
    env), then `script_dir / "config.json"`. Only sources that are actually
    set contribute a candidate; the script_dir fallback always does, so the
    list is never empty and the caller can just take the first entry.

    This is what makes config discovery cwd-independent -- a Scheduled Task
    with no working directory starts in C:\\Windows\\System32, where a
    relative "server/config.json" resolves to nothing. All three launchers
    pass an absolute --config, so cwd never matters for them; the
    script_dir fallback is for running the server by hand.
    """
    paths = []
    argv = list(argv) if argv is not None else []
    config_arg = None
    for i, token in enumerate(argv):
        if token == "--config" and i + 1 < len(argv):
            config_arg = argv[i + 1]
        elif token.startswith("--config="):
            config_arg = token.split("=", 1)[1]
    if config_arg is not None:
        paths.append(Path(config_arg))

    env_val = (env or {}).get("DESK_PANEL_CONFIG")
    if env_val:
        paths.append(Path(env_val))

    paths.append(Path(script_dir) / "config.json")
    return paths


def config_permission_warning(mode, platform):
    """Pure: a human-readable warning if `mode` (an os.stat().st_mode
    value) grants group or other permissions, else None.

    POSIX only -- config.json holds the brapi token, and `st_mode` is
    meaningless on Windows, where the real access control is the NTFS ACL,
    not a chmod bit. `platform` is whatever the caller passes as
    sys.platform ("linux", "darwin", "win32", ...), so this stays pure and
    testable without touching a filesystem.

    Always a warning, never a reason to refuse to start: this process is
    the login signal (invariant 2), and dying over a permission bit breaks
    that harder than a loose mode bit on a LAN-only box risks.
    """
    if platform == "win32":
        return None
    if mode & 0o077:
        return (
            f"warning: config.json is readable by group/other (mode "
            f"{oct(mode & 0o777)}); it holds the brapi token. Consider: "
            f"chmod 600 config.json"
        )
    return None


def check_python_version(version_info=None):
    """Pure: a readable error message if `version_info` is older than
    MIN_PYTHON, else None. Defaults to the running interpreter's own
    version. Guarding this explicitly matters because a too-old
    interpreter otherwise fails deep inside stdlib with a traceback that
    looks like a restart loop in journald or launchd, not a version
    mismatch.
    """
    if version_info is None:
        version_info = sys.version_info
    if tuple(version_info[:2]) < MIN_PYTHON:
        return (
            f"desk-panel server requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} "
            f"or newer (found {version_info[0]}.{version_info[1]})."
        )
    return None


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


class Server(HTTPServer):
    """HTTPServer with a platform-correct `allow_reuse_address`.

    On POSIX, SO_REUSEADDR just lets a restart rebind during TIME_WAIT --
    harmless, and http.server sets it to 1 by default. On Windows the same
    flag lets a *second* process bind the same port and steal connections,
    which is not a restart, it's fast user switching silently running two
    servers with nondeterministic answers. So on Windows we want the
    default socket behaviour (refuse, EADDRINUSE) instead of stdlib's 1.
    """

    allow_reuse_address = (os.name != "nt")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Desk panel PC server.")
    parser.add_argument(
        "--config",
        default=None,
        help="path to config.json (see config_search_paths for discovery order)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="load and validate config, print the result, and exit without binding a socket",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="append stdout/stderr here instead (Windows installer only, pythonw has no console)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    raw_argv = sys.argv[1:] if argv is None else list(argv)

    version_error = check_python_version()
    if version_error:
        print(version_error, file=sys.stderr)
        sys.exit(1)

    args = parse_args(raw_argv)

    if args.log_file:
        # pythonw has no console, and Task Scheduler cannot redirect stdout
        # without spawning `cmd /c`, which flashes a window -- so the
        # Windows installer points this at a file instead.
        log_fh = open(Path(args.log_file), "a", encoding="utf-8", buffering=1)
        sys.stdout = log_fh
        sys.stderr = log_fh
    else:
        # Explicit UTF-8 and line buffering: Windows does not default
        # stdout/stderr to UTF-8, and journald/launchd want output flushed
        # promptly rather than block-buffered.
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            try:
                stream.reconfigure(encoding="utf-8", line_buffering=True, write_through=True)
            except (AttributeError, ValueError):
                pass

    config_path = config_search_paths(raw_argv, os.environ, SCRIPT_DIR)[0]

    # A server that starts with silently-empty config looks healthy and
    # shows an empty panel -- worse than one that refuses to start with a
    # clear message. So this is fatal, not a fallback to DEFAULT_CONFIG.
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    if os.name != "nt":
        try:
            mode = os.stat(config_path).st_mode
        except OSError:
            mode = None
        if mode is not None:
            warning = config_permission_warning(mode, sys.platform)
            if warning:
                print(warning, file=sys.stderr)

    if args.check_only:
        print(f"config OK: {config_path}")
        return

    port = config.get("port", PORT)
    server = Server((HOST, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
