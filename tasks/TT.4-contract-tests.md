# TT.4 — Contract tests against the real APIs

Size: S · Pairs with: T3.3, T3.4 · Files: `server/tests/contract_upstream.py`

## Goal

Catch upstream schema changes — without letting the network into normal CI runs.

## Steps

1. `server/tests/contract_upstream.py`, named so the default discovery pattern (`test*.py`)
   does not pick it up.
2. Guard every test:

   ```python
   @unittest.skipUnless(os.environ.get("RUN_CONTRACT_TESTS"), "requires network")
   ```

3. Call brapi and Open-Meteo for real and assert on **shape, not values**: the expected keys
   exist and have the expected types. Prices change by the minute; the schema should not.
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

- Pact is the formal pattern for this. It is an external dependency for two endpoints, and this
  project does not take dependencies ([ADR 0009](../docs/adr/0009-testing-strategy.md)).
- Worth running manually every month or so, and any time the panel shows something odd.
