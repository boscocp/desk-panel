# TT.1 — Extract `format.js` and test it

Size: S · Pairs with: T1.2 · Files: `web/js/format.js`, `web/test/format.test.js`,
`web/js/app.js`

## Goal

Get the logic out of the DOM code and under test. Node's built-in runner has no DOM, which is
exactly the constraint that forces this separation — and the separation is an improvement
([ADR 0006](../docs/adr/0006-no-framework-web-layer.md)).

## Steps

1. Create `web/js/format.js` with **pure functions only** — no `document`, no `window`:
   - `formatPrice(value, currency)`
   - `formatChange(pct)` → sign, one decimal, percent
   - `changeClass(pct)` → `"up"` / `"down"` / `"flat"`
   - `weatherLabel(code)` → WMO code to a short human label
   - `isNight(now, start, end)` → handles the midnight wrap
2. Export for both worlds: an `export` for the browser, plus a CommonJS fallback so
   `node:test` can require it without a build step.
3. Rewrite `app.js` to import from it. `app.js` should end up with almost no logic left.
4. `web/test/format.test.js` using `node:test` and `node:assert`.

## Acceptance

```bash
node --test "web/test/**/*.test.js"
```

Exit code 0. And `grep -rn "document\.\|window\." web/js/format.js` returns nothing — if it
does, the function belongs in `app.js`, not here.

## Notes

- Cover the cases that are actually wrong in practice: negative change, zero change, a
  six-figure crypto price, an unknown weather code, and `isNight` spanning midnight.
- `node:test` has been stable since Node 20. No dependency, no config file, nothing to install.
