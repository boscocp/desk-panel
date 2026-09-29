#!/usr/bin/env python3
"""OAuth for the two calendars, standard library only (server/CLAUDE.md).

ADR 0017 is the decision, and this module is where its read-only rule is
enforced in code. The two providers use different flows, and neither was a
free choice:

    Google     installed-app flow: a loopback redirect to 127.0.0.1 with PKCE
               S256. Google's device authorization grant was the first plan and
               cannot work, because the scopes it allows include no Calendar
               scope at all
               (developers.google.com/identity/protocols/oauth2/limited-input-device).
    Microsoft  device code flow, as a public client: no secret, with a short
               code the owner types into a browser on any machine
               (learn.microsoft.com/entra/identity-platform/v2-oauth2-device-code).

**The granted scope is checked, not assumed.** Both token endpoints say what
they actually granted, and `check_scope` refuses any grant that carries a scope
outside a short read-only list. A consent screen with a box the owner ticked by
mistake must not leave a write token on the desk.

Everything that talks to the network takes its `post` as a parameter, so the
unit tests hand in a fake one and nothing here needs a socket. The only I/O
that stays is `TokenStore`, whose whole job is one file.
"""
import base64
import hashlib
import json
import os
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from server.upstream import TIMEOUT_S

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned.readonly"

# `common` rather than `consumers` or `organizations`: the owner connects both a
# personal account and a work one (ADR 0017), and one authority serves both.
# The token request must use the same authority as the device code request.
MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
MICROSOFT_DEVICE_CODE_URL = MICROSOFT_AUTHORITY + "/devicecode"
MICROSOFT_TOKEN_URL = MICROSOFT_AUTHORITY + "/token"
MICROSOFT_SCOPE = "Calendars.ReadBasic offline_access"

# What a grant may contain, per provider, and nothing else. The calendar scope
# is required; the rest are identity scopes that read a name and nothing more,
# listed because a provider may add them on its own (a Microsoft registration
# starts with User.Read, and Google adds `openid` when asked for a profile).
# Every entry is read-only. Adding one that is not would be a change to
# ADR 0017, not to this table.
REQUIRED_SCOPES = {
    "google": {GOOGLE_SCOPE},
    "microsoft": {"calendars.readbasic"},
}
ALLOWED_SCOPES = {
    "google": {
        GOOGLE_SCOPE,
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    },
    "microsoft": {
        "calendars.readbasic",
        "offline_access",
        "openid",
        "profile",
        "email",
        "user.read",
    },
}

# The prefix Microsoft puts on Graph scopes in a token response. It is removed
# before comparing, so `https://graph.microsoft.com/Calendars.ReadBasic` and
# `Calendars.ReadBasic` are the same grant.
GRAPH_RESOURCE = "https://graph.microsoft.com/"

# An access token is refreshed this long before it says it expires, so a
# request never leaves with a token that dies on the way.
EXPIRY_MARGIN_S = 60

# RFC 8628 section 3.5: poll every 5 s unless told otherwise, and add 5 s for
# this and every later request each time the server answers `slow_down`.
DEFAULT_POLL_INTERVAL_S = 5
SLOW_DOWN_STEP_S = 5


class OAuthError(Exception):
    """A token endpoint said no, or said something that is not a grant.

    `code` is the endpoint's `error` value (`invalid_grant`, `expired_token`,
    ...) or a word of this module's own. The message never contains a token,
    a code or a verifier: it names the endpoint and the error, which is what
    the log needs and all it may have (ADR 0017).
    """

    def __init__(self, code, message=None):
        super().__init__(message or code)
        self.code = code


class ScopeError(OAuthError):
    """The grant is not the read-only one that was asked for."""

    def __init__(self, message):
        super().__init__("scope", message)


def post_form(url, fields, timeout=TIMEOUT_S):
    """POST `fields` form-encoded to `url` and return the decoded JSON body.

    An error status is not an exception here. Both token endpoints answer a
    refused grant with a 400 and a JSON `error`, and `authorization_pending`
    is a 400 that means "ask again". So the body is returned for the caller
    to read, and OAuthError is raised only when there is no JSON to read at
    all. The fields never appear in a message, because they are where the
    secrets are.
    """
    data = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001 - reading the error body is best effort
            raw = b""
        if not raw:
            raise OAuthError("http", f"HTTP {exc.code} from {url}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise OAuthError("network", f"cannot reach {url}: {exc}") from None
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise OAuthError("format", f"{url} did not return JSON") from None
    if not isinstance(body, dict):
        raise OAuthError("format", f"{url} did not return a JSON object")
    return body


def _granted(provider, scope_text):
    """Pure: the set of scopes in a token response's `scope` field, normalised."""
    scopes = set()
    for scope in str(scope_text or "").split():
        if provider == "microsoft":
            if scope.lower().startswith(GRAPH_RESOURCE):
                scope = scope[len(GRAPH_RESOURCE):]
            scope = scope.lower()
        scopes.add(scope)
    return scopes


def check_scope(provider, scope_text):
    """Pure: raise ScopeError unless `scope_text` is a read-only calendar grant.

    Two ways to fail, and both mean nothing is stored. The grant may be
    missing the calendar scope, because Google lets the owner untick it on
    the consent screen. Or it may carry a scope outside `ALLOWED_SCOPES`, a
    broader one or a write one, which is the case ADR 0017 exists for.
    """
    granted = _granted(provider, scope_text)
    missing = REQUIRED_SCOPES[provider] - granted
    if missing:
        raise ScopeError(
            f"{provider} did not grant {', '.join(sorted(missing))}; "
            f"the calendar cannot be read without it")
    extra = granted - ALLOWED_SCOPES[provider]
    if extra:
        raise ScopeError(
            f"{provider} granted more than read-only access "
            f"({', '.join(sorted(extra))}); refusing to keep the token")


def _token_or_raise(provider, body, endpoint):
    """Pure: a token response -> the response, after its error and scope checks."""
    if "error" in body:
        raise OAuthError(str(body.get("error")), f"{provider} {endpoint}: {body.get('error')}")
    if not isinstance(body.get("access_token"), str) or not body["access_token"]:
        raise OAuthError("format", f"{provider} {endpoint}: no access_token in the response")
    check_scope(provider, body.get("scope"))
    return body


# --- Google: installed-app flow with PKCE -------------------------------------


def pkce_pair(token_bytes=secrets.token_bytes):
    """`(verifier, challenge)` for PKCE S256 (RFC 7636).

    43 characters of verifier from 32 random bytes, which is RFC 7636's own
    recommendation, and the challenge is its SHA-256, base64url without
    padding.
    """
    verifier = _b64url(token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def google_auth_url(client_id, redirect_uri, challenge, state):
    """Pure: the URL the owner opens to consent.

    `access_type` is not sent: Google always returns a refresh token to an
    installed app (developers.google.com/identity/protocols/oauth2/native-app).
    `prompt=consent` is, so that reconnecting an account that already
    consented still returns a grant the scope check can read.
    """
    query = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "consent",
    })
    return f"{GOOGLE_AUTH_URL}?{query}"


def google_exchange_code(client_id, client_secret, code, verifier, redirect_uri,
                         post=post_form):
    """The redirect's `code` -> the token response, scope-checked."""
    body = post(GOOGLE_TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    body = _token_or_raise("google", body, "code exchange")
    if not isinstance(body.get("refresh_token"), str) or not body["refresh_token"]:
        raise OAuthError("format", "google code exchange: no refresh_token in the response")
    return body


def google_refresh(client_id, client_secret, refresh_token, post=post_form):
    """A refresh token -> a new access token response, scope-checked.

    Google documents no rotation for its own refresh tokens, so the response
    normally carries none, and the stored one stays.
    """
    body = post(GOOGLE_TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    return _token_or_raise("google", body, "refresh")


def google_revoke(token, post=post_form):
    """Ask Google to drop every scope the token's project was granted.

    Best effort, and the caller deletes the local copy either way: a token
    Google no longer knows is already the result wanted.
    """
    return post(GOOGLE_REVOKE_URL, {"token": token})


# --- Microsoft: device code flow ----------------------------------------------


def microsoft_device_code(client_id, post=post_form):
    """Start the device code flow: `{device_code, user_code, verification_uri, ...}`."""
    body = post(MICROSOFT_DEVICE_CODE_URL, {"client_id": client_id, "scope": MICROSOFT_SCOPE})
    if "error" in body:
        raise OAuthError(str(body.get("error")), f"microsoft device code: {body.get('error')}")
    for key in ("device_code", "user_code", "verification_uri"):
        if not isinstance(body.get(key), str) or not body[key]:
            raise OAuthError("format", f"microsoft device code: no {key} in the response")
    return body


def microsoft_poll(client_id, device, post=post_form, sleep=time.sleep, clock=time.monotonic):
    """Poll the token endpoint until the owner has signed in, or it is over.

    Keeps polling only on `authorization_pending` and `slow_down`, which are
    the two answers RFC 8628 section 3.5 says mean "ask again", and adds 5 s
    to the interval for good on each `slow_down`. Microsoft's own table does
    not list `slow_down`; the RFC does, and honouring it costs nothing.
    Everything else, `authorization_declined` and `expired_token` included,
    stops here with that error.
    """
    interval = _positive_int(device.get("interval"), DEFAULT_POLL_INTERVAL_S)
    deadline = clock() + _positive_int(device.get("expires_in"), 900)
    while True:
        sleep(interval)
        if clock() > deadline:
            raise OAuthError("expired_token", "microsoft sign-in: the code expired")
        body = post(MICROSOFT_TOKEN_URL, {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": device["device_code"],
        })
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += SLOW_DOWN_STEP_S
            continue
        body = _token_or_raise("microsoft", body, "sign-in")
        if not isinstance(body.get("refresh_token"), str) or not body["refresh_token"]:
            raise OAuthError(
                "format", "microsoft sign-in: no refresh_token (was offline_access granted?)")
        return body


def microsoft_refresh(client_id, refresh_token, post=post_form):
    """A refresh token -> a token response carrying a *new* refresh token.

    Microsoft replaces the refresh token on every use and asks the client to
    keep the new one and delete the old
    (learn.microsoft.com/entra/identity-platform/refresh-tokens), which is
    why the server writes its own token file (ADR 0017).
    """
    body = post(MICROSOFT_TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
        "scope": MICROSOFT_SCOPE,
    })
    return _token_or_raise("microsoft", body, "refresh")


def _positive_int(value, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


# --- The token file -----------------------------------------------------------


class TokenStore:
    """`calendar-tokens.json`: one refresh token per account, and nothing else.

    Access tokens are never written. They last an hour and live in memory;
    a file holding them would only widen what a stolen copy is worth.

    Written the only safe way a secret can be written. The data goes to a
    temporary file in the same directory, created with mode 0600 before a
    byte goes in, and then `os.replace` swaps it into place. A crash
    mid-write leaves the old file whole, and at no moment is there a copy
    anyone else can read. On Windows the mode bits mean nothing and the
    protection is the ACL of the user's own profile, as it is for
    `config.toml`.
    """

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        """`{account: {"refresh_token": ...}}`, or `{}` when there is no file yet."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Never the content in the message: it is a file of tokens.
            raise OAuthError("store", f"{self.path} is not valid JSON") from None
        return data if isinstance(data, dict) else {}

    def refresh_token(self, account):
        entry = self.load().get(account)
        if isinstance(entry, dict) and isinstance(entry.get("refresh_token"), str):
            return entry["refresh_token"] or None
        return None

    def put(self, account, refresh_token):
        data = self.load()
        data[account] = {"refresh_token": refresh_token}
        self._write(data)

    def delete(self, account):
        data = self.load()
        if data.pop(account, None) is not None:
            self._write(data)

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".calendar-tokens.", dir=self.path.parent)
        try:
            # mkstemp already creates the file 0600 on POSIX. Set again rather
            # than trusted, because this is the one line the file's safety
            # rests on.
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def tokens_permission_warning(mode, platform, path):
    """Pure: a warning if the token file at `path` is readable by anyone else.

    The same rule `config_permission_warning` applies to the brapi token. It
    is a warning and never a refusal to start, because this process is the
    login signal (invariant 2). The writer above never produces such a file;
    a copy made by hand, or restored from a backup, can.
    """
    if platform == "win32" or mode is None:
        return None
    if mode & 0o077:
        return (f"warning: {path} is readable by group/other (mode {oct(mode & 0o777)}); "
                f"it holds calendar refresh tokens. Consider: chmod 600 {path}")
    return None


class Credentials:
    """An access token for one account, refreshed when it is about to expire.

    The refresh token comes from the store and, for Microsoft, goes back to it
    after every refresh, since the old one is not guaranteed to work again.
    `clock` is wall-clock seconds and is passed in, so the tests move time
    rather than wait for it.
    """

    def __init__(self, account, provider, config, store, post=post_form, clock=time.time):
        self.account = account
        self.provider = provider
        self.config = config
        self.store = store
        self.post = post
        self.clock = clock
        self._access_token = None
        self._expires_at = 0.0

    def access_token(self):
        now = self.clock()
        if self._access_token and now < self._expires_at - EXPIRY_MARGIN_S:
            return self._access_token
        refresh_token = self.store.refresh_token(self.account)
        if not refresh_token:
            raise OAuthError(
                "not_connected",
                f"calendar {self.account}: not connected; run "
                f"python server/calendar_login.py {self.provider} --account "
                f"{self.account.split('/', 1)[-1]}")
        try:
            body = self._refresh(refresh_token)
        except OAuthError:
            # A refused refresh is not retried with the same token on every
            # cycle; the cache already limits attempts to one per interval,
            # and the message tells the owner what to run.
            self._access_token = None
            raise
        rotated = body.get("refresh_token")
        if isinstance(rotated, str) and rotated and rotated != refresh_token:
            self.store.put(self.account, rotated)
        self._access_token = body["access_token"]
        self._expires_at = now + _positive_int(body.get("expires_in"), 3600)
        return self._access_token

    def _refresh(self, refresh_token):
        if self.provider == "google":
            return google_refresh(self.config.get("google_client_id", ""),
                                  self.config.get("google_client_secret", ""),
                                  refresh_token, post=self.post)
        return microsoft_refresh(self.config.get("microsoft_client_id", ""),
                                 refresh_token, post=self.post)
