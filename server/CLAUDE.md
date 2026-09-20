# Server layer

Python **3.11 or newer**, standard library only. No pip, no virtualenv, no requirements.txt.
That is a hard constraint: the server must run on a clean box with nothing installed, and
adding a dependency breaks that promise.

A floor, not a pin. It read "3.13"; the development machine has 3.14 and macOS ships no
`python3` at all. T3.11 guards the floor with a `sys.version_info` check, because otherwise a
too-old interpreter surfaces as a restart loop in journald rather than as a message.

## Rules specific to this layer

- **Keep the request handler dumb.** Python documents no way to exercise a
  `BaseHTTPRequestHandler` without a socket, so all real logic — config loading, provider
  response normalisation, payload assembly — lives in plain functions that tests call
  directly. The handler only routes and serialises.
- **This process is the login signal.** It is launched by a Scheduled Task with an "At log on"
  trigger. Do not turn it into a Windows Service, do not add auto-restart-on-boot: answering
  without a logged-in user reports the wrong thing (invariant 2).
- **Secrets stay here.** The brapi token is read from `config.toml`, which is gitignored. It
  must never be embedded in the APK or echoed in a response.
- **Config drives behaviour.** Tickers, city, intervals and the theme come from `config.toml`.
  If a change to what the panel shows requires rebuilding the APK, the design has been violated.
- **The config file is also the documentation.** `config.example.toml` is committed and carries
  the catalogue: what each key does, its default, and which values actually work. A key added to
  `DEFAULT_CONFIG` and not to the example is a key no owner ever finds out about, and TT.2 fails
  the build over it. `config.example.json` is the legacy twin, kept in step by the same test for
  as long as `config.json` is read at all (T3.12).
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
