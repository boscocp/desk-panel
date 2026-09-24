#!/usr/bin/env python3
"""Generic HTTP probe.

Standard library only, and deliberately independent of server.py and every
other module in this repository -- it has to be able to probe a machine
that has no checkout at all (T3.8/T3.9/T3.10 run it against a different
host over the LAN). The one exception is `--serve`, which starts the
sibling server.py as a subprocess purely to exercise it locally; it is
launched by path, never imported.

    probe.py --host H [--port P] --expect up|down [--timeout S]
    probe.py --serve --expect up            # starts server.py, probes, stops it
    probe.py --serve --url /action/x --method POST --expect-status 501
    probe.py --host H --url /quotes --expect-json-keys quotes,fx,crypto
    probe.py --serve --url /app --method HEAD --expect-header content-type=application/...

Exit 0 iff reality matched the expectation, 1 if it did not, 2 on a probe
error that is not itself an answer (bad hostname, permission error, the
child server failing to start).
"""
import argparse
import json
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path

DEFAULT_PORT = 8777
DEFAULT_URL = "/ping"
DEFAULT_METHOD = "GET"
DEFAULT_TIMEOUT = 3.0
SERVE_STARTUP_TIMEOUT = 10.0


class ProbeError(Exception):
    """A failure that is not itself "down" -- bad hostname, permission
    error, or a --serve child that never came up. Must never be mistaken
    for --expect down matching."""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Probe an HTTP endpoint.")
    parser.add_argument("--host", default=None, help="required unless --serve")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--method", default=DEFAULT_METHOD)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--expect", choices=["up", "down"], default=None)
    parser.add_argument("--expect-status", type=int, dest="expect_status", default=None)
    parser.add_argument(
        "--expect-header",
        dest="expect_header",
        action="append",
        default=None,
        metavar="NAME=VALUE",
        help=(
            "a response header that must be present with this value; repeatable. "
            "The name is case-insensitive and the value is compared exactly, minus "
            "surrounding whitespace"
        ),
    )
    parser.add_argument(
        "--expect-json-keys",
        dest="expect_json_keys",
        default=None,
        help="comma-separated keys that must all be present in the JSON response body",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="start this repo's server.py, probe it, then stop it",
    )
    args = parser.parse_args(argv)

    if (
        args.expect is None
        and args.expect_status is None
        and args.expect_json_keys is None
        and args.expect_header is None
    ):
        parser.error(
            "one of --expect, --expect-status, --expect-header or --expect-json-keys is required"
        )
    for pair in args.expect_header or []:
        if "=" not in pair:
            parser.error(f"--expect-header wants NAME=VALUE, got {pair!r}")
    if not args.serve and args.host is None:
        parser.error("--host is required unless --serve")
    if args.serve and args.host is None:
        args.host = "127.0.0.1"
    return args


def check(host, port, url, method, timeout):
    """One HTTP request. Returns ("up", status_code, body_bytes, headers) or
    ("down", None, b"", []).

    `headers` is a list of (name, value) pairs as the server sent them --
    order and case preserved, duplicates kept, because discarding either
    would make this unable to answer questions about the wire.

    "down" covers both a refused connection (nothing listening) and a
    timeout (a firewall dropping packets instead of refusing them) --
    the caller must not be able to tell them apart, by design. Anything
    else (a bad hostname, a permission error) is a genuine error and is
    raised as ProbeError instead of being folded into "down".
    """
    conn = HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request(method, url)
        response = conn.getresponse()
        status = response.status
        headers = list(response.getheaders())
        # Read it either way: the body is what --expect-json-keys needs, and
        # an unread response leaves the socket unusable for keep-alive.
        body = response.read()
        return "up", status, body, headers
    except (ConnectionRefusedError, socket.timeout, TimeoutError):
        return "down", None, b"", []
    except socket.gaierror as exc:
        raise ProbeError(f"cannot resolve host {host!r}: {exc}") from exc
    except OSError as exc:
        raise ProbeError(f"unexpected error probing {host}:{port}: {exc}") from exc
    finally:
        conn.close()


def mismatched_headers(headers, wanted):
    """Pure: which of `wanted` (NAME=VALUE strings) the response does not carry.

    Returns a list of readable complaints -- empty means every one matched.
    Header names are case-insensitive per RFC 9110; values are compared
    exactly, after stripping surrounding whitespace, because the assertion
    that matters here is a media type and a media type is not a substring
    question: `text/html` contains `text/htm`, and a check that accepted that
    would pass for the wrong server.

    A repeated header matches if any of its values does.
    """
    seen = {}
    for name, value in headers:
        seen.setdefault(name.lower(), []).append(value.strip())
    problems = []
    for pair in wanted:
        name, _, expected = pair.partition("=")
        key = name.strip().lower()
        expected = expected.strip()
        values = seen.get(key)
        if values is None:
            problems.append(f"no {name.strip()} header")
        elif expected not in values:
            problems.append(f"{name.strip()} is {values[0]!r}, wanted {expected!r}")
    return problems


def missing_json_keys(body, wanted):
    """Pure: which of `wanted` are absent from the JSON object in `body`.

    Returns a list -- empty means every key is there. A body that is not a
    JSON object counts as missing all of them, which is the right answer for
    an endpoint that returned an HTML error page with a 200.

    Presence only, never value: this is a contract check. A temperature can
    be judged by a human and by nothing else, which is why T3.4 puts the
    number in its manual check and the shape here.
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return list(wanted)
    if not isinstance(data, dict):
        return list(wanted)
    return [key for key in wanted if key not in data]


def evaluate(args):
    """Run one probe against args.host/port and compare to the expectation.

    Expectations combine with AND when more than one is given, so
    `--expect-status 200 --expect-json-keys a,b` fails if either does.
    """
    kind, status, body, headers = check(
        args.host, args.port, args.url, args.method, args.timeout
    )

    matched = True
    detail = ""
    if args.expect is not None:
        matched = matched and kind == args.expect
    if args.expect_status is not None:
        matched = matched and kind == "up" and status == args.expect_status
    if args.expect_header is not None:
        if kind != "up":
            matched = False
        else:
            wrong = mismatched_headers(headers, args.expect_header)
            if wrong:
                matched = False
                detail = " (" + "; ".join(wrong) + ")"

    if args.expect_json_keys is not None:
        wanted = [k.strip() for k in args.expect_json_keys.split(",") if k.strip()]
        if kind != "up":
            matched = False
        else:
            absent = missing_json_keys(body, wanted)
            if absent:
                matched = False
                detail = f" (missing JSON keys: {', '.join(absent)})"
    return matched, kind, status, detail


def port_is_taken(host, port, timeout=0.5):
    """True if something already accepts connections on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
        return True


def run_server_and_probe(args):
    """Start server.py as a child process, probe it, then stop it -- cleaning
    up the child even when the probe or the assertion fails, so a bad run
    never leaves the port bound for the next one."""
    # Refuse to run if the port is already busy. Without this, server.py fails
    # to bind, exits, and the readiness loop happily connects to whatever was
    # already there -- so --serve reports success for code it never started.
    # This is not hypothetical: T3.9 installs a systemd user unit on the
    # development machine listening on this very port, which would turn every
    # later --serve acceptance green against the installed service instead of
    # the working tree.
    if port_is_taken(args.host, args.port):
        raise ProbeError(
            f"{args.host}:{args.port} is already in use; --serve will not probe a "
            f"server it did not start. Stop the other listener first "
            f"(on Linux: systemctl --user stop desk-panel)."
        )
    server_path = Path(__file__).resolve().parent / "server.py"
    process = subprocess.Popen(
        [sys.executable, str(server_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + SERVE_STARTUP_TIMEOUT
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise ProbeError(
                    f"server.py exited early (code {process.returncode}): {stderr.strip()}"
                )
            kind, _, _, _ = check(args.host, args.port, "/ping", "GET", 0.5)
            if kind == "up":
                ready = True
                break
            time.sleep(0.1)
        if not ready:
            raise ProbeError(f"server.py did not become ready within {SERVE_STARTUP_TIMEOUT}s")
        return evaluate(args)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stderr:
            process.stderr.close()


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.serve:
            matched, kind, status, detail = run_server_and_probe(args)
        else:
            matched, kind, status, detail = evaluate(args)
    except ProbeError as exc:
        print(f"probe error: {exc}", file=sys.stderr)
        return 2

    description = f"{args.method} {args.host}:{args.port}{args.url} -> {kind}"
    if kind == "up":
        description += f" (status {status})"
    description += detail
    print(description)
    return 0 if matched else 1


if __name__ == "__main__":
    sys.exit(main())
