# 0001 — Java over Kotlin for the Android app

Status: accepted · 2026-09-13

## Context

The Android side of this project is small: one Activity, one WebView, a polling loop and two
window flags. Roughly a hundred lines.

Google's public position is "Kotlin-first", which is easy to read as "Kotlin-only". The owner
of this project is fluent in Java, TypeScript, Python and JavaScript, but not Kotlin. Choosing
Kotlin would mean learning a language to write a hundred lines of glue.

## Decision

Write the app in Java.

The official language page says Kotlin "is 100% interoperable with the Java programming
language" and that Google will "continue to provide support for using our APIs from the Java
programming language". Nothing in this app's surface — `Activity`, `WebView`,
`WindowManager.LayoutParams`, `PowerManager`, `BatteryManager` — is Kotlin-only; these are
platform APIs and language-agnostic by design.

The one area where Java genuinely loses is **Jetpack Compose**, which is Kotlin in practice.
This app uses a single WebView and no Compose, so that cost is not paid.

## Consequences

- The owner can read and maintain every line without a detour through a new language.
- Samples found online will often be Kotlin, and will need mental translation. For APIs this
  stable and this few, that is a small and bounded cost.
- If the UI ever grows beyond a WebView and Compose becomes attractive, this decision should be
  revisited — Compose is the one thing that would flip it.
- Gradle files still use the Kotlin DSL (`.kts`), which is the current default. That is
  configuration, not application code, and does not require knowing Kotlin.

## References

- <https://developer.android.com/kotlin/first>
- <https://developer.android.com/kotlin/interop>
