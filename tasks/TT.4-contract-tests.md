# TT.4 — Contract tests against the real APIs

Size: S · Prereqs: T3.3, T3.4 · Pairs with: T3.3, T3.4 · Files: `server/tests/contract_upstream.py`

Requires: network, and the real upstream APIs reachable

## Goal

Catch upstream schema changes — without letting the network into normal CI runs.

## Steps

1. `server/tests/contract_upstream.py`, named so the default discovery pattern (`test*.py`)
   does not pick it up.
2. Guard every test:

   ```python
   @unittest.skipUnless(os.environ.get("RUN_CONTRACT_TESTS"), "requires network")
   ```

3. Call **every upstream the panel calls** for real and assert on **shape, not values**: the
   expected keys exist and hold what the normalisers can read. Prices change by the minute; the
   schema should not.

   This line read "brapi and Open-Meteo" until wave 23, and by then the panel had five: brapi
   covers B3 and nothing else — crypto and FX both refuse without a token (T3.3 subtask 0), so
   they moved to Binance and AwesomeAPI — and the moon arrived from the USNO with T6.13. An
   upstream this file does not cover is one whose schema change reaches the desk as a blank
   card, which is the failure the whole task exists to precede.

   Assert that a number **parses**, not that it is typed: brapi sends JSON numbers where
   Binance and AwesomeAPI send the same quantities as strings, every normaliser runs `float()`
   over both, and a provider moving between the two costs this project nothing.
4. On failure, the message should say which field went missing, so the fix is obvious without
   re-running by hand.
5. When a contract test fails, the fixtures in TT.2 are stale — re-record them as part of
   fixing it.

## Acceptance

```bash
python -m unittest discover -s server/tests -t .                       # these are skipped
RUN_CONTRACT_TESTS=1 python -m unittest discover -s server/tests -t . -p "contract_*.py"
```

The first skips them; the second runs them and passes.

## Notes

- **The assertions get their own tests before they are trusted.** Wave 22 built
  `--expect-header` and proved it could fail four ways before using it as a gate; the helpers
  here are the same kind of thing and are covered offline by `server/tests/test_contract_helpers.py`.
  Two of those cases are the ones that matter: `float(True)` is 1.0, so a price that became a
  flag passes a naive check, and an empty `results` array has to fail with a message rather than
  raise `IndexError` naming no field at all.
- The skip guard has to leave a mark of its own. `unittest.skipUnless` is **the identity
  function** when its condition holds, so once `RUN_CONTRACT_TESTS` is set a decorator built
  only out of it leaves nothing behind — and a case added to the file without the decorator
  becomes invisible to everything but review, while being the one case that opens a socket from
  `make check`.
- Pact is the formal pattern for this. It is an external dependency for two endpoints, and this
  project does not take dependencies ([ADR 0009](../docs/adr/0009-testing-strategy.md)).
- Worth running manually every month or so, and any time the panel shows something odd.
