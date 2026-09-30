# 0018 — The panel's traffic is private on the LAN, and `/ping` is not

Status: accepted · 2026-09-30 (T9.4)
Amends [ADR 0004](0004-server-is-login-signal-and-proxy.md), whose server spoke plain HTTP only,
[ADR 0015](0015-the-panel-can-act-on-the-pc.md), whose argument against a token assumed `/app`
hands the APK to anyone, and [ADR 0017](0017-calendars-are-personal-data.md), whose stated cost
was "anyone on the same Wi-Fi can read the titles".

## Context

T9.1 put the owner's meeting titles on `/quotes`. The Host check keeps a web page from reading
them. Any device on the Wi-Fi still could, in two ways:

- **by asking**, since `curl http://<pc>:8777/quotes` answers anyone;
- **by listening**, since the traffic is plain HTTP, and on WPA2-PSK anyone who knows the Wi-Fi
  password can decrypt other clients' traffic.

The owner asked for both to be closed. [The spike](../spikes/2026-panel-tls.md) measured the
recommended design on the Redmi, and it works.

## Decision

**Design 1: HTTPS with a pinned certificate, plus a shared key.** Design 2, encrypting the
`agenda` block by hand, was not needed. The choice it would have forced, between relaxing
stdlib-only and hand-building a cipher from HMAC, is therefore not made.

- **Data and presses move to their own TLS port**, `tls_port`, default 8778.
  - The server uses Python's own `ssl`: TLS 1.2 or newer, and the owner's certificate and key
    from `config.toml`.
  - The handshake runs on the request thread (`do_handshake_on_connect=False`), with a 10 s
    timeout, so a stalled client can never stall the listener.
- **Every data route and every press needs `X-Panel-Key`**, compared as SHA-256 digests with
  `hmac.compare_digest`, so neither the value nor the length leaks through timing.
  - Without the key the answer is 401, and a wrong key gets the same 401.
  - On the plain port it is 401 even with the right key. By then the key has already crossed
    the air in clear, and answering would teach the owner that it works.
- **`/ping` stays plain HTTP on the plain port, and open.** It is the login signal (invariant
  2), and it carries two facts: somebody is logged in, and their display is on
  ([ADR 0020](0020-the-panel-sleeps-with-the-display.md)).
  - Behind TLS, an expired, replaced or mistyped certificate would read as a logout. That is
    the one failure this project exists to avoid, and a panel that goes dark over a
    certificate is much harder to diagnose than one showing a data error.
  - The two facts it leaks are not worth that risk.
  - It also keeps the cost off the battery: 30 pings a minute stay plain, and TLS touches only
    the data poll, which makes two requests a minute and runs only while the panel is lit.
- **The phone pins the PCs' own certificates.** `PC_CERTS` in `.env` lists them. The build
  concatenates them into `raw/pc_certs.pem` and names that file as the only trust anchor in the
  existing `domain-config`, so no system CA is trusted for a LAN address.
  - The certificate is a self-signed leaf with the PC's IP in `subjectAltName`, made by
    `server/make_cert.py` with the `openssl` the host already has (ADR 0003).
  - Its curve must be named: an explicit one is refused by Android with `decode_error`, as
    measured in the spike.
- **All three settings or none, on each side.**
  - On the server, `panel_key`, `tls_cert` and `tls_key` go together. Two out of three is a
    startup error.
  - In the build, `PANEL_KEY` and `PC_CERTS` go together. One without the other is a build
    error.
  - None is the panel as it always was: open, over plain HTTP. The server says so at every
    start. A fresh clone still works in a browser, as `docs/RUNNING-LOCALLY.md` promises.
- **`/app` is off by default** (`serve_apk = false`). The APK carries the key, so whoever
  downloads the APK has the key. This is what ADR 0015's argument against a token was missing:
  a token is worth something once the APK is not handed out.

## Consequences

- With the key, a device on the Wi-Fi that asks gets 401, and one that listens sees TLS on 8778
  and nothing but `/ping` on 8777. The ADR 0017 cost becomes "anyone who has the APK", which is
  a much smaller set, and `calendar_show_titles = false` remains the answer for the desk itself.
- **Every listed PC has to be in the same mode.** A private APK talks TLS to every host in
  `PC_IP`, so a PC without its own certificate stops giving the panel data. The screen still
  follows it, because `/ping` is unchanged.
- **Cleartext stays permitted for the PCs' addresses.** `/ping` needs it, and a `domain-config`
  cannot scope cleartext to one port. What keeps data off plain HTTP is the phone's own URLs,
  plus the server's 401 on the plain port.
- Rotating the key or a certificate means a rebuild and a reinstall, like any other change to
  `.env` (ADR 0013).
- **Not yet measured:** a packet capture from a third device, a press over TLS from the phone's
  buttons, and anything on the Windows PC. T9.4's manual check lists them.
