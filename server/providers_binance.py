#!/usr/bin/env python3
"""Crypto quotes, from Binance's public API.

Here rather than in brapi because brapi's crypto endpoint answers
`401 MISSING_TOKEN` and `config.json` carries no token — measured 2026-09-19,
recorded in providers_brapi.py. The T3.3 task file named Binance as the
key-free replacement for exactly this outcome.

    GET /api/v3/ticker/24hr?symbols=["BTCUSDT","ETHUSDT"]

    [{"symbol": "BTCUSDT", "lastPrice": "81470.00000000",
      "priceChangePercent": "1.016", ...}, ...]

Two things about that shape are worth naming, because both are places a
careless reading produces a plausible wrong number:

- **Every value is a string.** `lastPrice` is `"81470.00000000"`, not
  `81470.0`. Rendered without conversion it sorts and formats as text.
- **The symbol is a pair, not a coin.** Config says `BTC`; Binance says
  `BTCUSDT`. The suffix is added on the way out and stripped on the way back,
  so nothing downstream ever sees it — the same discipline the FX provider
  applies to its three spellings of a currency pair.

USDT, not USD: Binance has no USD spot pair for these. The panel labels
crypto in USD (web/js/app.js), and a stablecoin pegged 1:1 is the honest
approximation at the precision a desk panel displays.
"""
import json

from server.upstream import UpstreamError, get_json

TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
KLINES_URL = "https://api.binance.com/api/v3/klines"

# What a bare coin from the config is quoted against.
QUOTE_ASSET = "USDT"


def to_pair(coin):
    """Pure: `BTC` -> `BTCUSDT`. Already-suffixed input is left alone, so a
    config that spells out the pair keeps working."""
    coin = str(coin).upper()
    return coin if coin.endswith(QUOTE_ASSET) else coin + QUOTE_ASSET


def to_coin(pair):
    """Pure: `BTCUSDT` -> `BTC`. The inverse, for the way back out."""
    pair = str(pair).upper()
    return pair[: -len(QUOTE_ASSET)] if pair.endswith(QUOTE_ASSET) else pair


def fetch(coins, get=get_json):
    """Ask Binance for `coins`. The seam TT.2 patches.

    The `symbols` parameter is a JSON array inside a query string, which is
    Binance's own convention and not a mistake: it is built with `json.dumps`
    rather than string formatting so a coin name can never break out of it.
    """
    if not coins:
        return []
    pairs = [to_pair(coin) for coin in coins]
    # Separators without spaces: Binance rejects the array if urlencoding
    # turns ", " into "%2C%20" inside it.
    symbols = json.dumps(pairs, separators=(",", ":"))
    return get(f"{TICKER_URL}?symbols={symbols}")


def fetch_history(coin, days, get=get_json):
    """One coin's recent daily candles. The seam TT.2 patches."""
    return get(f"{KLINES_URL}?symbol={to_pair(coin)}&interval=1d&limit={int(days)}")


# A kline is a twelve-element array, and the close is the fifth. Binance
# documents it positionally and nothing in the response names it, so the index
# is written down here rather than left as a bare 4 in the middle of a
# comprehension -- reading the high (2) or the open (1) by mistake would give
# a chart that is plausible and wrong.
KLINE_CLOSE = 4


def normalise_history(raw):
    """Pure: the klines response -> `[close, ...]`, oldest first.

    Binance already returns oldest first, unlike AwesomeAPI, so this does not
    reverse. The two providers disagreeing about direction is exactly the kind
    of thing that draws a rise as a fall, which is why each has its own test
    against a recorded response.
    """
    if not isinstance(raw, list):
        return []
    closes = []
    for candle in raw:
        if not isinstance(candle, list) or len(candle) <= KLINE_CLOSE:
            continue
        close = _number(candle[KLINE_CLOSE])
        if close is not None:
            closes.append(close)
    return closes


def load_history(coins, days, get=get_json):
    """`{coin: [closes oldest-first]}` for every coin that answered."""
    coins = list(coins or [])
    history = {}
    failures = []
    for coin in coins:
        try:
            history[to_coin(coin)] = normalise_history(fetch_history(coin, days, get=get))
        except UpstreamError as exc:
            failures.append(exc)
    # See providers_awesomeapi.load_history: a total failure must not be
    # cached as an answer.
    if coins and failures and not history:
        raise failures[0]
    return history


def normalise(raw):
    """Pure: Binance's response -> `[{symbol, price, changePct}, ...]`.

    `symbol` is the bare coin, matching what the config asked for, so the
    panel shows BTC rather than BTCUSDT.
    """
    if not isinstance(raw, list):
        return []

    crypto = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        price = _number(entry.get("lastPrice"))
        symbol = entry.get("symbol")
        if not symbol or price is None:
            continue
        crypto.append({
            "symbol": to_coin(symbol),
            "price": price,
            "changePct": _number(entry.get("priceChangePercent")) or 0.0,
        })
    return crypto


def _number(value):
    """Pure: `value` as a float, or None. Binance sends every number as a
    string, so this is the normal path here rather than a fallback."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load(coins, get=get_json):
    """fetch + normalise, with upstream failure surfaced as UpstreamError."""
    return normalise(fetch(coins, get=get))


__all__ = ["KLINES_URL", "KLINE_CLOSE", "QUOTE_ASSET", "TICKER_URL", "UpstreamError",
           "fetch", "fetch_history", "load", "load_history", "normalise",
           "normalise_history", "to_coin", "to_pair"]
