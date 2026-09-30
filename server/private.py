"""The panel's own traffic, kept between the PC and the phone (T9.4, ADR 0018).

Two things close the two ways a device on the Wi-Fi could read the panel:

- **By listening.** Data and presses move to their own port, `tls_port`, served
  with Python's own `ssl` and a certificate the phone pins. Nothing on that
  port is readable on the air, including on WPA2-PSK, where anyone with the
  password can decrypt other clients' traffic.
- **By asking.** Every data route and every press needs `X-Panel-Key`, a
  random value shared by `config.toml` and the APK. Without it, or on the plain
  port, the answer is 401.

`/ping` stays on the plain port, open and in cleartext. It carries two facts,
somebody is logged in and whether their display is on, and it is the login
signal (invariant 2). Putting it behind a certificate would turn an expired
or mistyped certificate into "the owner is logged out", on the one signal this
project must never get wrong. ADR 0018 has the argument.

All three settings, or none. With none the server behaves as it always did,
open to the LAN, so a fresh clone still works in a browser. That state is the
owner's to choose, and `main` says out loud at every start that it is in it.
"""
import hashlib
import hmac
import os
import ssl
import sys

KEY_HEADER = "X-Panel-Key"
TLS_PORT = 8778

# 32 characters is 192 bits from `secrets.token_urlsafe(24)`. `make_cert.py`
# prints a 43-character one. Shorter than this is a password somebody typed,
# and a key the LAN can guess closes nothing.
MIN_KEY_LENGTH = 32

# How long a TLS client may sit on a connection without finishing a request.
# The handshake runs in the request thread, not in accept(), so a stalled
# client costs one thread for this long and never the listener.
TLS_TIMEOUT_S = 10


def settings(config):
    """Pure: (key, cert, key_file, port) when the traffic is private, or None.

    Raises ValueError for a half configuration: a key without a certificate
    would send it in cleartext on every request, and a certificate without a
    key would encrypt answers anyone may ask for. Either one is a misconfigured
    panel that looks private, which is worse than an open one that says so.
    """
    key = (config.get("panel_key") or "").strip()
    cert = (config.get("tls_cert") or "").strip()
    key_file = (config.get("tls_key") or "").strip()
    given = [name for name, value in
             (("panel_key", key), ("tls_cert", cert), ("tls_key", key_file)) if value]
    if not given:
        return None
    if len(given) != 3:
        missing = sorted({"panel_key", "tls_cert", "tls_key"} - set(given))
        raise ValueError(
            f"{', '.join(given)} set without {', '.join(missing)}: private traffic needs "
            f"all three (docs/adr/0018-the-panel-traffic-is-private.md)")
    if len(key) < MIN_KEY_LENGTH:
        raise ValueError(
            f"panel_key is {len(key)} characters; it needs at least {MIN_KEY_LENGTH}. "
            f"`python server/make_cert.py --key` prints one")
    port = config.get("tls_port", TLS_PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError(f"tls_port must be a port number, not {port!r}")
    if port == config.get("port"):
        raise ValueError(f"tls_port {port} is the plain port; /ping needs that one to itself")
    return key, cert, key_file, port


def key_matches(expected, given):
    """Constant-time: whether `given` is the panel key.

    Both sides are hashed first. `hmac.compare_digest` is constant-time for
    equal lengths only, and comparing the raw strings would tell a patient
    client how long the key is. A missing header is compared like a wrong one.
    """
    want = hashlib.sha256(expected.encode("utf-8")).digest()
    got = hashlib.sha256((given or "").encode("utf-8")).digest()
    return hmac.compare_digest(want, got)


def authorized(config, request_headers, channel):
    """Whether a data route or a press may answer on this `channel`.

    Open (no key configured): always, as before T9.4. Private: only on the TLS
    channel, and only with the key. A key sent to the plain port is refused
    even when it is right, because it has already crossed the air in clear and
    answering would teach the owner that it works.
    """
    private = settings(config)
    if private is None:
        return True
    if channel != "tls" or request_headers is None:
        return False
    return key_matches(private[0], request_headers.get(KEY_HEADER))


def context(cert, key_file):
    """The server's TLS context: TLS 1.2 or newer, the owner's certificate."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key_file)
    return ctx


def key_file_warning(mode, platform, path):
    """Pure: a warning if the TLS private key is readable by anyone but the owner."""
    if mode is None or platform == "win32":
        return None
    if mode & 0o077:
        return (f"warning: {path} is mode {mode & 0o777:o}; the TLS private key should be "
                f"0600 (chmod 600 {path})")
    return None


def check(config):
    """Everything `--check-only` should catch before the owner meets it at the desk.

    Returns the settings or None, and raises ValueError with a message that
    names the file. Loads the certificate for real, so a key that does not
    match its certificate fails here and not at the first poll.
    """
    private = settings(config)
    if private is None:
        return None
    _, cert, key_file, _ = private
    for path in (cert, key_file):
        if not os.path.isfile(path):
            raise ValueError(f"{path} not found; `python server/make_cert.py` makes one")
    try:
        context(cert, key_file)
    except (ssl.SSLError, OSError) as exc:
        raise ValueError(f"cannot load {cert} with {key_file}: {exc}") from None
    if os.name != "nt":
        try:
            mode = os.stat(key_file).st_mode
        except OSError:
            mode = None
        warning = key_file_warning(mode, sys.platform, key_file)
        if warning:
            print(warning, file=sys.stderr)
    return private
