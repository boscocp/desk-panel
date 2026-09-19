# Architecture

## The problem

A phone on a desk, powered from the PC's USB port, cannot tell when the PC goes away. USB rails
stay energised in S5, so the battery API reports "charging" with the machine fully shut down.
Any signal derived from power is wrong before it starts.

Meanwhile no web API can wake a sleeping Android screen. That single fact is why this is a
native app and not a web page.

## Shape

```
┌─ Redmi Note 10 (Android 12) ───────┐      ┌─ Windows 11 ──────────────────┐
│                                    │      │                               │
│  MainActivity (Java)               │      │  server.py (stdlib only)      │
│   ├─ screen state ◀── PcState      │      │   ├─ GET /ping                │
│   ├─ PcPoller   ──── http:// ──────┼──────┼─▶ ├─ GET /quotes  → brapi.dev │
│   └─ DataPoller ──── http:// ──────┼──────┼─▶ ├─ GET /weather → open-meteo│
│         │                          │      │   ├─ GET /app     (the APK)   │
│         │ evaluateJavascript       │      │   └─ POST /action/{id} → 501  │
│         ▼                          │      │                               │
│  WebView                           │      │  Scheduled Task "At log on"   │
│   https://appassets.android…       │      │  ⇒ answers only while a user  │
│   assets from the APK              │      │     is logged in              │
│   no network of its own            │      │                               │
└────────────────────────────────────┘      └───────────────────────────────┘
                                              brapi token lives here, and
                                              only here
```

## The three invariants

### 1. JavaScript never calls `fetch`

`WebViewAssetLoader` serves the panel from `https://appassets.androidplatform.net/`. A
`fetch()` from that origin to `http://<pc-ip>:8777` is mixed content, and Android's own guidance
advises against `MIXED_CONTENT_ALWAYS_ALLOW`.

Rather than weaken the WebView, the network moves to Java. `PcPoller` and `DataPoller` use
`HttpURLConnection`; results arrive in the page through `window.onPcState()` and
`window.onData()`. `MIXED_CONTENT_NEVER_ALLOW` stays set, and cleartext is permitted for
exactly one address in `network_security_config.xml`.

Consequence worth naming: the WebView becomes pure presentation, which is what makes it
testable in a plain browser with `web/js/mock.js`.

See [ADR 0002](adr/0002-native-owns-network-io.md).

### 2. The server is the login signal

A Scheduled Task with an "At log on" trigger runs inside the user's session. "It answers" and
"a user is logged in" are therefore the same statement. A Windows Service would have the same
uptime and the wrong meaning.

Because the server has to exist anyway, the data goes through it too. The brapi token stays on
the PC; tickers and city become server config, so changing what the panel shows never means
rebuilding the APK.

See [ADR 0004](adr/0004-server-is-login-signal-and-proxy.md).

### 3. Screen state follows PC state, never a timeout

- Online: hold `FLAG_KEEP_SCREEN_ON`.
- Offline: clear it, let Android sleep the screen.
- Back online: `setTurnScreenOn(true)` with `setShowWhenLocked(true)`.

Documented fallback if MIUI proves unreliable at waking: `screenBrightness = 0f` plus a black
render. On AMOLED that is nearly indistinguishable from off, but it is not off, and the display
keeps drawing power.

See [ADR 0005](adr/0005-real-screen-sleep.md).

## Data flow

1. `PcPoller` hits `/ping` every 2s while online, backing off to 15s while offline. It is owned
   by `PanelService`, a foreground service, and not by the Activity: the screen going out stops
   the Activity, and a loop that stopped with it could never notice the PC coming back
   ([ADR 0014](adr/0014-poll-loop-outlives-the-screen.md)).
2. Transitions drive `PcState`, a plain class with no Android imports — which is why it is unit
   tested on the JVM.
3. `PcState` changes do three things: log `state=`, take or drop the offline wake lock, and hand
   the transition to `MainActivity`, which sets the screen state and calls `window.onPcState()`.
   Coming back online the service also raises the Activity, because `setTurnScreenOn` fires when
   the window becomes visible and nothing else would make it.
4. While online, `DataPoller` hits `/quotes` and `/weather` on their own slower intervals and
   pushes results through `window.onData()`. While offline it is paused entirely.
5. `web/js/app.js` renders. All formatting logic lives in `web/js/format.js` as pure functions.
6. Every transition emits a logcat marker on the `DeskPanel` tag. The E2E suite asserts on
   those, because Android exposes no documented way to read screen state
   ([ADR 0009](adr/0009-testing-strategy.md)).

## Validated parameters

| Item | Value | Source |
|---|---|---|
| `compileSdk` / `targetSdk` | 36 | [Play target API requirements](https://developer.android.com/google/play/requirements/target-sdk) |
| `minSdk` | 26 (device is API 31) | — |
| Local assets | `WebViewAssetLoader` + `AssetsPathHandler`, `androidx.webkit` | [docs](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content) |
| Brightness | `WindowManager.LayoutParams.screenBrightness`; `-1f` system, `0f` minimum; window-scoped, no permission | [reference](https://developer.android.com/reference/android/view/WindowManager.LayoutParams) |
| Cleartext | `network_security_config.xml`, `domain-config` scoped to the PC IP | [Network Security Config](https://developer.android.com/privacy-and-security/security-config) |
| Weather | Open-Meteo, no key, CORS `*`, 10k req/day | [terms](https://open-meteo.com/en/terms) |
| Quotes | brapi.dev, 15k req/month free; token required beyond four sample tickers | [pricing](https://brapi.dev/pricing) |

## v2: shortcut buttons

Not built, but the shape is fixed so it can be added without rework. `POST /action/{id}`
returns 501 today. When implemented, `id` indexes a **closed allowlist in server config** that
maps to a Steam URI or an executable path. The request carries an id and nothing else — never a
command, a path or an argument. The web layer renders whatever buttons the config declares, and
a `@JavascriptInterface` bridge forwards the id to native, which forwards it to the server.
