# desk-panel

Turns a spare Android phone into a desk panel for a Windows PC: clock, B3 quotes, crypto, FX
and weather, in a cyberpunk-neon skin — visible **only while the PC is powered on and logged
in**. When the PC shuts down, the phone screen sleeps.

Built for a Redmi Note 10 (Android 12, MIUI 14) lying in a landscape stand, powered from the
PC's USB port.

## Why this exists

USB ports stay energised in S5, so a phone on your desk never learns that the PC went away.
No web API can wake an Android screen, and the one off-the-shelf app that does this well
(Fully Kiosk) is paid and closed source. Glance, Macro Deck, Deckboard, station-dashboard and
IntraHub were all evaluated — none of them blank the display when the host disappears, which
is the entire requirement.

## How it works

```
┌─ Phone ────────────────────────────┐      ┌─ Windows 11 ──────────────────┐
│  MainActivity (Java)               │      │  server.py (stdlib only)      │
│   ├─ keeps screen on / lets sleep  │      │   ├─ GET /ping                │
│   ├─ PcPoller   ──── http:// ──────┼──────┼─▶ ├─ GET /quotes  → brapi.dev │
│   └─ DataPoller ──── http:// ──────┼──────┼─▶ └─ GET /weather → open-meteo│
│         │ evaluateJavascript       │      │                               │
│         ▼                          │      │  Scheduled Task "At log on"   │
│  WebView — assets from the APK,    │      │  ⇒ only answers while logged  │
│  no network of its own             │      │     in                        │
└────────────────────────────────────┘      └───────────────────────────────┘
```

Three decisions carry the design, and each has an ADR:

- **All network I/O is native.** The WebView is served over `https://` from inside the APK, so
  JavaScript calling a `http://` LAN address would be mixed content. Moving the fetch to Java
  removes the problem instead of working around it. ([ADR 0002](docs/adr/0002-native-owns-network-io.md))
- **The server is both the login signal and the data proxy.** A Scheduled Task with an
  "At log on" trigger only answers while someone is logged in — which is exactly the signal we
  want. Since it exists anyway, routing quotes through it keeps the API token off the phone.
  ([ADR 0004](docs/adr/0004-server-is-login-signal-and-proxy.md))
- **The screen genuinely sleeps.** Not a black render with the display still lit.
  ([ADR 0005](docs/adr/0005-real-screen-sleep.md))

## Getting started

The Android toolchain runs entirely in Docker — no JDK, no Android SDK and no Android Studio
on the host. See [docs/BUILD.md](docs/BUILD.md).

```bash
docker compose -f docker/compose.yml run --rm build ./gradlew assembleDebug
python server/server.py
make check
```

Then install on the phone by browsing to `http://<pc-ip>:8777/app` — no cable, no adb.
See [docs/INSTALL-PHONE.md](docs/INSTALL-PHONE.md).

## Documentation

| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | The full picture and the three invariants |
| [BUILD.md](docs/BUILD.md) | Containerised toolchain, building, signing |
| [INSTALL-PHONE.md](docs/INSTALL-PHONE.md) | Installing, and the MIUI toggles that matter |
| [SERVER-SETUP.md](docs/SERVER-SETUP.md) | Scheduled Task, firewall, static IP, BIOS |
| [DEVICE-CARE.md](docs/DEVICE-CARE.md) | Battery, heat and burn-in — and the honest limits |
| [TESTING.md](docs/TESTING.md) | Four test layers, all standard library |
| [LOCAL-MODELS.md](docs/LOCAL-MODELS.md) | Driving the repo with a local model instead of Opus — which one, and its limits |
| [adr/](docs/adr/) | Decision records, including the options that were rejected |

Work is tracked as self-contained task files under [tasks/](tasks/), indexed by
[tasks/STATUS.md](tasks/STATUS.md).

## Status

Bootstrap. Specs, decision records and task breakdown are written; no product code yet.

## License

MIT
