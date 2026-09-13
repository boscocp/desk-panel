# 0007 — Rejecting Capacitor and Trusted Web Activity

Status: accepted · 2026-09-13

## Context

The owner writes TypeScript comfortably and does not write Kotlin. Two routes promise an
Android app without native code, and both deserved a real evaluation rather than a dismissal:

- **Trusted Web Activity / PWABuilder** — wrap a web app as an APK.
- **Capacitor** — write the app in TypeScript, let the framework bridge to native.

## Decision

Neither. Write the small native app (ADR 0001).

**TWA fails on capability.** It is documented as a way to open web content "using a protocol
based on Custom Tabs" — a full-screen Chrome instance, not a gateway to Android APIs. Web
content inside it reaches hardware only through standard Web APIs. The Screen Wake Lock API
exists and would cover *keeping* the screen on, but **there is no standard Web API for screen
brightness**, and none for waking a sleeping screen. Those are precisely the capabilities this
project is built around. TWA cannot express the core feature.

**Capacitor fails on cost/benefit.** It does avoid writing Java. It does **not** avoid the
Android toolchain: its own setup docs require Android Studio and the Android SDK to produce an
APK, which is the heavy part we were trying to escape (ADR 0003). Brightness control is not in
the first-party plugin list; it comes from the community plugin
`@capacitor-community/screen-brightness`, which is itself a thin wrapper over the same
`Window.setAttributes` call we would write ourselves. So the trade is: add Node, npm, a plugin
ecosystem and a third-party dependency, in exchange for not writing about a hundred lines of
Java — while still installing the SDK either way.

## Consequences

- One toolchain (Docker + Gradle) instead of two (Docker + Gradle + Node/npm/Capacitor).
- No third-party dependency on the critical path of the core feature.
- The owner writes Java, which they already know, rather than TypeScript that compiles into a
  plugin call into Java.
- **Revisit if** the app grows substantial UI logic that would benefit from sharing code with a
  web project. At one Activity and one WebView, it does not.

## References

- <https://developer.chrome.com/docs/android/trusted-web-activity/overview>
- <https://developer.chrome.com/docs/capabilities/web-apis/wake-lock>
- <https://capacitorjs.com/docs/getting-started/environment-setup>
- <https://capacitorjs.com/docs/plugins>
