#!/usr/bin/env python3
"""Connect, or disconnect, one calendar account. Run on the PC, by the owner.

    python server/calendar_login.py google --account personal
    python server/calendar_login.py microsoft --account work
    python server/calendar_login.py google --account personal --disconnect

The account must already be listed in `calendar_accounts` in config.toml, so
the token file can never hold a token for an account the server does not know
about. What lands in `calendar-tokens.json`, beside the config, is the refresh
token and nothing else, and only after the granted scope has been checked as
read-only (ADR 0017).

**Google** opens the consent page in this PC's browser and waits for the
redirect on `127.0.0.1`, on a port the OS picks. The listener takes one
request, checks `state`, and is gone. It is not the panel's server and it is
not on the LAN. On a machine with no browser the URL is printed instead, and
a browser elsewhere needs an SSH tunnel to reach the port. That is Google's
design for installed apps, not a shortcut taken here.

**Microsoft** prints a short code and a URL. Open it anywhere, type the code,
and this command finishes on its own.

Nothing here prints a token, and the only code printed is Microsoft's
`user_code`, which is the one meant for a human to read.
"""
import argparse
import http.server
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import oauth, providers_calendar  # noqa: E402
from server.server import (SCRIPT_DIR, ConfigError, _allow_reuse_address,  # noqa: E402
                           config_search_paths, load_config, tokens_path_for)

LOGIN_TIMEOUT_S = 300


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("provider", choices=providers_calendar.PROVIDERS)
    parser.add_argument("--account", required=True,
                        help="the `name` of an entry in calendar_accounts")
    parser.add_argument("--config", help="config file (default: the server's own search)")
    parser.add_argument("--disconnect", action="store_true",
                        help="forget this account's token (and revoke it, for Google)")
    parser.add_argument("--no-browser", action="store_true",
                        help="print Google's consent URL instead of opening it")
    return parser.parse_args(argv)


class _LoopbackServer(http.server.HTTPServer):
    """127.0.0.1 only, one request at a time, and no SO_REUSEADDR on Windows.

    On Windows that flag lets a second process bind the same port and take
    the connection, which is the reason `server.Server` turns it off too.
    """

    allow_reuse_address = _allow_reuse_address(os.name)

    def __init__(self, state):
        super().__init__(("127.0.0.1", 0), _Redirect)
        self.expected_state = state
        self.result = None


class _Redirect(http.server.BaseHTTPRequestHandler):
    """The one request Google's redirect makes. Records its query and says so."""

    # Per connection. Without it a connection that sends nothing (a
    # browser's speculative preconnect is enough) blocks `handle_request`
    # for ever, and the login deadline is never checked.
    timeout = 10

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        state = query.get("state", [""])[0]
        if not secrets.compare_digest(state.encode("utf-8"),
                                      self.server.expected_state.encode("utf-8")):
            # A favicon request, or any local process guessing at the port:
            # answered, and the wait goes on. Only the redirect carrying the
            # state this run generated can end it, so a forged one cannot
            # abort the login either.
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.server.result = {k: v[0] for k, v in query.items()}
        ok = "code" in self.server.result
        body = ("Connected. You can close this tab." if ok
                else "Not connected. See the terminal.").encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        # The request line carries the authorisation code; it is not logged.
        pass


def google_login(config, open_browser=True):
    """Run the loopback flow and return the checked token response."""
    client_id = config.get("google_client_id", "")
    client_secret = config.get("google_client_secret", "")
    verifier, challenge = oauth.pkce_pair()
    state = secrets.token_urlsafe(24)

    server = _LoopbackServer(state)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
    url = oauth.google_auth_url(client_id, redirect_uri, challenge, state)
    try:
        print("Open this URL in a browser on this PC and approve read-only access:\n")
        print(f"  {url}\n", flush=True)
        if open_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + LOGIN_TIMEOUT_S
        while server.result is None:
            if time.monotonic() > deadline:
                raise oauth.OAuthError("timeout", "no redirect within five minutes")
            server.handle_request()
    finally:
        server.server_close()

    result = server.result
    if "error" in result:
        raise oauth.OAuthError(result["error"], f"google consent: {result['error']}")
    if "code" not in result:
        raise oauth.OAuthError("format", "the redirect carried no code")
    return oauth.google_exchange_code(client_id, client_secret, result["code"], verifier,
                                      redirect_uri)


def microsoft_login(config):
    client_id = config.get("microsoft_client_id", "")
    device = oauth.microsoft_device_code(client_id)
    # Microsoft's own sentence names the URL and the code, in the account's
    # language when it can.
    print(device.get("message") or
          f"Open {device['verification_uri']} and enter {device['user_code']}", flush=True)
    return oauth.microsoft_poll(client_id, device)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    raw = ["--config", args.config] if args.config else []
    config_path = config_search_paths(raw, os.environ, SCRIPT_DIR, exists=os.path.exists)[0]
    try:
        config = load_config(config_path)
        accounts = providers_calendar.accounts_from_config(config.get("calendar_accounts"))
    except (ConfigError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    account = f"{args.provider}/{args.account}"
    if (args.provider, args.account) not in accounts:
        print(f"{account} is not in calendar_accounts in {config_path}; add it there first",
              file=sys.stderr)
        return 1
    store = oauth.TokenStore(tokens_path_for(config_path))

    if args.disconnect:
        token = store.refresh_token(account)
        if token and args.provider == "google":
            try:
                oauth.google_revoke(token)
                print("Google revoked the grant.")
            except oauth.OAuthError as exc:
                print(f"Google did not revoke it ({exc.code}); remove the app yourself at "
                      f"https://myaccount.google.com/permissions", file=sys.stderr)
        elif args.provider == "microsoft":
            print("Microsoft has no endpoint to revoke one app's token. Remove the app at "
                  "https://myapplications.microsoft.com (work or school) or "
                  "https://account.live.com/consent/Manage (personal).")
        store.delete(account)
        print(f"{account}: token removed from {store.path}")
        return 0

    missing = providers_calendar.missing_client_ids([(args.provider, args.account)], config)
    if missing:
        print(f"set {', '.join(missing)} in {config_path} first; see docs/SERVER-SETUP.md",
              file=sys.stderr)
        return 1

    try:
        if args.provider == "google":
            grant = google_login(config, open_browser=not args.no_browser)
        else:
            grant = microsoft_login(config)
    except oauth.OAuthError as exc:
        print(f"{account}: not connected: {exc}", file=sys.stderr)
        return 1

    store.put(account, grant["refresh_token"])
    print(f"{account}: connected, read-only ({grant.get('scope')}). Token in {store.path}; "
          f"restart the server to pick it up sooner than calendar_interval_s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
