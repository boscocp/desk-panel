# 0002 — Native code owns all network I/O

Status: accepted · 2026-09-13

## Context

The panel UI is HTML/CSS/JS packaged inside the APK and served by `WebViewAssetLoader`, which
hosts it at `https://appassets.androidplatform.net/`. An `https://` origin is what makes the
page a secure context.

The app must poll a plain-HTTP endpoint on the LAN (`http://<pc-ip>:8777/ping`) to learn
whether the PC is awake. A `fetch()` from the page to that address is, by definition, mixed
content. Android's own guidance on loading in-app content advises **against**
`MIXED_CONTENT_ALWAYS_ALLOW` and recommends serving content over a single scheme.

The obvious workaround — flip the WebView to `MIXED_CONTENT_ALWAYS_ALLOW` — weakens the
WebView globally to solve a problem of our own making.

## Decision

The WebView never performs network requests. All I/O happens in Java, and results are pushed
into the page:

```java
webView.evaluateJavascript("window.onPcState(true)", null);
webView.evaluateJavascript("window.onData(" + json + ")", null);
```

`setMixedContentMode(MIXED_CONTENT_NEVER_ALLOW)` stays set. Cleartext to the PC is permitted by
`network_security_config.xml`, scoped to that one address, and applies to the native HTTP
client rather than to page content.

## Consequences

- Mixed content stops being a thing to manage. There is no `http://` subresource anywhere.
- The web layer becomes pure presentation: data in, pixels out. That makes it testable in a
  plain browser with fixtures, and it is why `web/js/mock.js` exists.
- Native code grows by one polling class. Small, and it has to exist anyway for the PC signal.
- The API token never reaches the phone, because the phone never calls the upstream API.
- **Constraint for future work:** adding a `fetch` to the web layer silently reintroduces the
  problem. This is invariant 1 in `CLAUDE.md` for that reason.

## References

- <https://developer.android.com/develop/ui/views/layout/webapps/load-local-content>
- <https://developer.android.com/privacy-and-security/security-config>
