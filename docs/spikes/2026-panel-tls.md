# Spike: TLS between the panel and the PC (T9.4)

2026-09-30, wave 39. Redmi Note 10 (Android 12, MIUI 14) against the owner's Mac (Python 3.14,
OpenSSL 3.6.2) on the home Wi-Fi. **Answer: design 1 works on this phone, and it shipped.**
[ADR 0018](../adr/0018-the-panel-traffic-is-private.md) is the decision this informs.

## The four questions

### Does `HttpURLConnection` accept a self-signed certificate pinned for an IP address?

**Yes**, with one condition that cost the spike most of its time.

- The certificate is pinned as `<trust-anchors><certificates src="@raw/pc_certs"/>` inside the
  existing `domain-config`. The domain match works for a bare IPv4 address, exactly as the
  cleartext pin always has.
- Hostname verification for an IP reads `subjectAltName` `IP:…`, as expected. A leaf with
  `CA:FALSE`, `digitalSignature` and `serverAuth` is accepted as its own trust anchor.
- **The first certificate failed every handshake with `TLSV1_ALERT_DECODE_ERROR`**, sent by the
  phone. macOS's `/usr/bin/openssl` is LibreSSL 3.3.6, and it wrote the P-256 public key with
  **explicit curve parameters** (`prime-field …` in `asn1parse`) instead of the named-curve OID.
  Android's BoringSSL refuses such keys.
  - Capping the server at TLS 1.2 did not help the phone, which ruled out the TLS version.
  - macOS's own curl also failed on TLS 1.3 with the same certificate, which misled the spike
    towards a protocol problem for a while.
  - `-pkeyopt ec_param_enc:named_curve` fixed both clients, on TLS 1.3. `make_cert.py` always
    passes it, and `test_private.MakeCertTests` pins it.
- After the fix: `data=ok` on the phone over `https://192.168.3.97:8778`, TLS 1.3,
  `TLS_AES_256_GCM_SHA384`.

### What does TLS cost?

**Almost nothing, because `/ping` stays plain.**

- Measured from the Mac with curl, five runs: TCP connect 2.5 to 5.5 ms, TLS done at 6.3 to
  11.3 ms, whole request 7 to 13 ms. A plain `/ping` takes 8 to 19 ms on the same path.
- `DataPoller` makes one cycle a minute (`INTERVAL_MS = 60_000`), which is two requests and so
  two handshakes. `PcPoller` makes 30 plain pings a minute. TLS therefore touches about 6% of
  the requests, and only while the panel is lit. The data poll stops offline and idle.
- No keep-alive or resumption work was needed. The server is still HTTP/1.0 (one connection per
  request), and at two handshakes a minute this does not matter.

**`/ping` stays plain HTTP.** It carries "somebody is logged in" and "their display is on", and it
is the login signal. With TLS on it, an expired, replaced or mistyped certificate would read as a
logout, on the one signal this project must not get wrong. ADR 0018 argues it.

### How is the certificate made, with nothing installed?

**With the `openssl` every host already has.** `server/make_cert.py` drives it:

| Host | `openssl` | Measured |
|---|---|---|
| macOS | `/usr/bin/openssl`, LibreSSL 3.3.6 | yes, needs `named_curve` (above) |
| macOS with Homebrew | OpenSSL 3.6.2 | yes |
| The Docker image | OpenSSL 3.0.13 | `openssl version` only |
| Windows | Git for Windows' OpenSSL | not measured |
| Linux | distribution OpenSSL | not measured |

The private key is written under a 077 umask, then `chmod 600`, into `server/tls/`, which is
gitignored. `check_secrets.py` already refuses a PEM private key by content and by name. The
build refuses a `PC_CERTS` file that contains one.

### Do two PCs behind one `PC_IP` still work?

**By construction, and not measured.** Each PC runs `make_cert.py --ip <its address>`. `PC_CERTS`
lists every certificate, and the build concatenates them into one `raw/pc_certs.pem`, which
Android reads whole. Only the Mac was on the LAN during the spike, so a second certificate has not
been exercised on the device.

The two PCs must agree on the mode. A private APK talks TLS to every listed PC, so a PC without
its own certificate stops giving the panel data. `/ping`, and so the screen, are unaffected.

## What was not measured

- A packet capture from a third device. It needs root on the capturing machine, and the Mac is
  the server. The claim "no title in clear" rests on the design: data only on 8778, and 401 on
  8777, which was measured with curl from the LAN.
- A press over TLS from the phone's buttons. The URL and the header are unit-tested, and the
  route's 401 without the key is too.
- Windows. Its Python and OpenSSL are presumably the same classes as the Mac's, but that is an
  assumption, not a measurement.
