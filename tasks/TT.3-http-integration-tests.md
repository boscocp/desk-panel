# TT.3 — Two HTTP integration tests

Size: S · Prereqs: T3.3, T3.7 · Pairs with: T3.3 · Files: `server/tests/test_http.py`

## Goal

Cover the actual HTTP path — routing, status codes, headers, serialisation — which the pure
function tests deliberately skip.

Two tests. Not a suite. The logic is already covered in TT.2; this only proves the wiring.

## Steps

1. Start an `HTTPServer` on **port 0** so the OS assigns a free port, and read the real port
   back from `server.server_address`. Hard-coded ports make tests fail on a busy machine.
2. Run it on a background thread in `setUpClass`, shut it down in `tearDownClass`.
3. Patch the upstream providers so the fixtures are served — this must still not touch the
   network.
4. Test 1: `/ping` returns 200 with the expected body.
5. Test 2: `/quotes` returns 200, `Content-Type: application/json`, and a payload matching the
   T1.2 contract shape.
6. Also assert `/nonexistent` returns 404 and `POST /action/x` returns 501.

## Acceptance

```bash
python -m unittest discover -s server/tests -t .
```

Exit code 0, with no port conflicts on repeated runs.

## Notes

- Shut the server down properly or the test process hangs. `shutdown()` then `server_close()`,
  in that order.
- Resist growing this file. Every new case here is slower and more fragile than the same case
  as a pure function test.
