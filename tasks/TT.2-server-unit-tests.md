# TT.2 — Server unit tests and fixtures

Size: M · Pairs with: T3.3, T3.4 · Files: `server/tests/test_*.py`,
`server/tests/fixtures/*.json`

## Goal

Cover the server's logic with no network access at all, so CI is fast and deterministic.

## Steps

1. Record real responses once, by hand, into `server/tests/fixtures/`:
   `brapi_quotes.json`, `brapi_crypto.json`, `openmeteo_forecast.json`,
   `openmeteo_geocoding.json`. **Strip the token from anything recorded.**
2. Test the pure functions directly: `load_config`, both `normalise` functions, cache expiry,
   and the stale-fallback path.
3. Patch the outbound call with `unittest.mock.patch` — patch the one small function that
   performs the HTTP request, which is why T3.3 isolates it.
4. Cover the failure paths too: upstream 500, malformed JSON, timeout, missing field. These are
   what actually happen.
5. No test in this file may touch the network. Contract tests live separately, in TT.4.

## Acceptance

```bash
python -m unittest discover -s server/tests -t .
```

Exit code 0. Run it again with the network disconnected — it must behave identically. That is
the real check.

## Notes

- Python documents no way to drive a `BaseHTTPRequestHandler` without a socket, which is why
  the logic lives in plain functions. If a test here needs a server, the code is in the wrong
  place — move it, do not improvise a fake socket.
- Fixtures go stale as upstream evolves. That is what TT.4 is for.
