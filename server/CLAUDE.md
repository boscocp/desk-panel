# Server layer

Python 3.13, **standard library only**. No pip, no virtualenv, no requirements.txt. That is a
hard constraint: the server must run on a clean Windows box with nothing installed, and adding
a dependency breaks that promise.

## Rules specific to this layer

- **Keep the request handler dumb.** Python documents no way to exercise a
  `BaseHTTPRequestHandler` without a socket, so all real logic — config loading, provider
  response normalisation, payload assembly — lives in plain functions that tests call
  directly. The handler only routes and serialises.
- **This process is the login signal.** It is launched by a Scheduled Task with an "At log on"
  trigger. Do not turn it into a Windows Service, do not add auto-restart-on-boot: answering
  without a logged-in user reports the wrong thing (invariant 2).
- **Secrets stay here.** The brapi token is read from `config.json`, which is gitignored. It
  must never be embedded in the APK or echoed in a response.
- **Config drives behaviour.** Tickers, city and intervals come from `config.json`. If a change
  to what the panel shows requires rebuilding the APK, the design has been violated.
- **Bind to the LAN, never to the internet.** No port forwarding, no `0.0.0.0` exposure beyond
  the local network, and the firewall rule is scoped to the Private profile.
- `POST /action/{id}` is a v2 placeholder and returns 501. When it is implemented it takes a
  **closed allowlist of ids** from config — never a command, path or argument from the request.

## Run and test

```bash
python server/server.py                                  # foreground
python -m unittest discover -s server/tests -t .         # unit, no network
RUN_CONTRACT_TESTS=1 python -m unittest discover -s server/tests -t . -p "contract_*.py"
```

Unit tests must never touch the network — they patch the outbound call and read fixtures from
`tests/fixtures/`. The contract tests are the only ones allowed out, and they are skipped
unless `RUN_CONTRACT_TESTS` is set.
