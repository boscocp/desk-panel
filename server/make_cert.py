#!/usr/bin/env python3
"""Make this PC's TLS certificate and the panel key (T9.4, ADR 0018).

    python server/make_cert.py --ip 192.168.1.100     # certificate + key + a panel key
    python server/make_cert.py --key                  # a new panel key only

The Python standard library cannot write an X.509 certificate, so this drives
`openssl`, which every host this project supports already has: macOS ships
LibreSSL as /usr/bin/openssl, Git for Windows ships OpenSSL, and every Linux
desktop has it. Nothing is installed (ADR 0003). With none on PATH, the
project's Docker image has one; the message says how.

What it writes, under `--out` (default `server/tls/`, gitignored):

- `<ip>.pem` -- the certificate. Public: the phone pins it, so its path goes
  in `PC_CERTS` in `.env` and the APK is rebuilt.
- `<ip>.key` -- the private key, mode 0600. It never leaves this PC, and
  `scripts/check_secrets.py` refuses it by name and by content.

The certificate is a self-signed leaf for exactly one IP address, in
`subjectAltName`, because Android checks an IP host against the SAN and never
against the CN. Ten years, because it is pinned rather than trusted through a
chain: expiry would buy nothing but a dark panel, and rotating it is a rebuild
either way.
"""
import argparse
import ipaddress
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parent / "tls"
DAYS = 3650


def new_key():
    """A panel key: 32 random bytes, URL-safe, 43 characters."""
    return secrets.token_urlsafe(32)


def openssl_argv(openssl, ip, cert, key, days=DAYS):
    """Pure: the `openssl req` command for a self-signed P-256 leaf for `ip`.

    Every extension is spelled out rather than left to the local openssl.cnf,
    because OpenSSL 3 and LibreSSL disagree on the defaults: OpenSSL adds
    CA:TRUE, LibreSSL adds nothing, and LibreSSL encodes the curve explicitly. The phone should not see a different
    certificate depending on which PC made it.
    """
    return [
        openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
        # Named, not explicit: macOS's LibreSSL otherwise writes the curve's
        # parameters out in full, and Android's BoringSSL refuses such a key
        # with a TLS decode_error (measured on the Redmi, 2026-09-30).
        "-pkeyopt", "ec_param_enc:named_curve",
        "-nodes", "-days", str(days), "-subj", f"/CN=desk-panel {ip}",
        "-addext", f"subjectAltName=IP:{ip}",
        "-addext", "basicConstraints=critical,CA:FALSE",
        "-addext", "keyUsage=critical,digitalSignature",
        "-addext", "extendedKeyUsage=serverAuth",
        "-keyout", str(key), "-out", str(cert),
    ]


def make(ip, out, openssl):
    """Write `<ip>.pem` and `<ip>.key` under `out`. Refuses to overwrite:
    replacing a pinned certificate is a rebuild of the APK, and doing it by
    accident is a panel that goes dark at the next restart."""
    out.mkdir(parents=True, exist_ok=True)
    cert, key = out / f"{ip}.pem", out / f"{ip}.key"
    for path in (cert, key):
        if path.exists():
            raise SystemExit(f"{path} exists; delete both files first to replace them, "
                             f"then rebuild the APK")
    # The key is written by openssl, so the umask is what keeps it private
    # between its creation and the chmod below.
    previous = os.umask(0o077)
    try:
        done = subprocess.run(openssl_argv(openssl, ip, cert, key), capture_output=True,
                              text=True, check=False)
    finally:
        os.umask(previous)
    if done.returncode != 0:
        raise SystemExit(f"openssl failed:\n{done.stderr.strip()}")
    if os.name != "nt":
        os.chmod(key, 0o600)
        # Public, and read by the Gradle build inside a container.
        os.chmod(cert, 0o644)
    return cert, key


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ip", help="this PC's LAN address, as in PC_IP")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--key", action="store_true", help="print a new panel key and stop")
    args = parser.parse_args(argv)

    if args.key:
        print(new_key())
        return
    if not args.ip:
        parser.error("--ip is required (or --key for a key alone)")
    try:
        ip = ipaddress.IPv4Address(args.ip)
    except ValueError:
        parser.error(f"not an IPv4 address: {args.ip}")

    openssl = shutil.which("openssl")
    if openssl is None:
        raise SystemExit(
            "no openssl on PATH. Git for Windows ships one "
            "(C:\\Program Files\\Git\\usr\\bin\\openssl.exe), or use the project's image:\n"
            "  docker compose -f docker/compose.yml run --rm build openssl ...")
    cert, key = make(str(ip), args.out, openssl)
    print(f"certificate: {cert}\nprivate key: {key} (stays on this PC)\n")
    print("In server/config.toml:")
    print(f'  panel_key = "{new_key()}"')
    print(f'  tls_cert = "{cert}"\n  tls_key = "{key}"\n')
    print("In .env, then rebuild and reinstall the APK:")
    print("  PANEL_KEY=<the same panel_key>")
    print(f"  PC_CERTS={cert}   (comma-separated, one per PC)")


if __name__ == "__main__":
    main(sys.argv[1:])
