# 0006 — No framework and no build step in the web layer

Status: accepted · 2026-09-13

## Context

The panel is a handful of cards on a fixed 2400×1080 landscape screen: a clock, a few rows of
quotes, a weather block. It has one viewport, one user and one device. There is no routing, no
forms, no navigation and no shared state worth managing.

A framework would bring a `node_modules`, a bundler, a lockfile and a build step between
editing a file and seeing it on the phone.

## Decision

Plain HTML, CSS and JavaScript. No framework, no bundler, no transpiler, no `package.json`
dependency. `android/app/build.gradle.kts` points `assets.srcDirs` at `../../web`, so the files
shipped in the APK are literally the files in the repo.

## Consequences

- Editing the panel is: save the file, rebuild, look. Nothing in between.
- `web/index.html` opens directly in Chrome for development, with `web/js/mock.js` supplying
  fixtures through the same `window.onData()` entry point the native layer uses in production.
- No supply chain. Nothing to audit, nothing to update, nothing to break on a transitive bump.
- Tests run on Node's built-in runner with zero dependencies (ADR 0009).
- **Cost:** no reactive rendering. DOM updates are written by hand. At this size that is a few
  `textContent` assignments, which is cheaper than the machinery that would avoid them.
- **Design pressure, deliberately kept:** because the test runner has no DOM, all logic worth
  testing lives in `web/js/format.js` as pure functions, and DOM code stays thin enough not to
  need tests. The constraint improves the structure rather than fighting it.
