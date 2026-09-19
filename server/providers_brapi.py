#!/usr/bin/env python3
"""B3 stock quotes, from brapi.dev.

=========================================================================
T3.3 subtask 0 — what brapi actually serves, measured 2026-09-19
=========================================================================

The task file opened with an unconfirmed question: does brapi cover FX and
crypto, and what needs a token. Answered by asking the API rather than the
docs, because the docs describe the endpoints without giving their shapes.

    GET /api/v2/stocks/quote?symbols=PETR4,VALE3,ITUB4  -> 200, no token
    GET /api/quote/PETR4,VALE3,ITUB4                    -> 200, no token
    GET /api/v2/crypto?coin=BTC,ETH&currency=BRL        -> 401 MISSING_TOKEN
    GET /api/v2/currency?currency=USD-BRL,EUR-BRL       -> 401 MISSING_TOKEN

So **brapi covers stocks here and nothing else**. Crypto and FX both refuse
without a token, and `config.json` carries an empty `brapi_token`. The task
file pre-approved the fallback for exactly this outcome, and it is what the
panel uses: Binance for crypto (providers_binance.py), AwesomeAPI for FX
(providers_awesomeapi.py). Both are key-free.

That is also why this module is named for one upstream and does one thing. A
`providers_brapi.py` that reached out to Binance would be a lie in the one
place — the filename — where a reader is entitled to trust it.

**Two response shapes, both live.** `/api/v2/stocks/quote` nests the numbers
under `data`; the older `/api/quote/<symbols>` returns them flat. Both
answered 200 without a token on the same day, so `normalise` reads either.
This is not defensive habit: the free tier is the part of an API most likely
to be moved, and a panel that silently renders nothing is the failure this
project keeps designing against.

**Tokens.** PETR4, MGLU3, VALE3 and ITUB4 are the documented free sample set
and are what `config.json` ships. Any other ticker needs a token, which stays
in config.json and is sent as a header, never in the query string — see
`upstream._safe` for why that distinction is load-bearing.
"""
from server.upstream import UpstreamError, get_json

QUOTE_URL = "https://brapi.dev/api/v2/stocks/quote"

# The four tickers brapi documents as answering without a token. Not enforced
# — a token makes the whole exchange available — but named here so a panel
# that comes back empty on a fresh install has an explanation in one grep.
FREE_TIER_SYMBOLS = ("PETR4", "MGLU3", "VALE3", "ITUB4")


def fetch(symbols, token="", get=get_json):
    """Ask brapi for `symbols`. The seam TT.2 patches.

    `get` is injected rather than imported at the call site so a test can
    replace exactly this module's outbound call — see server/CLAUDE.md.
    """
    if not symbols:
        return {"results": []}
    url = f"{QUOTE_URL}?symbols={','.join(symbols)}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return get(url, headers=headers)


def normalise(raw):
    """Pure: brapi's response -> the T1.2 contract shape.

    Returns `[{symbol, price, changePct}, ...]`, skipping any entry that does
    not carry a usable price. Skipping rather than raising is deliberate: one
    delisted ticker in a list of five should cost that row, not the panel.
    """
    # isinstance, not `raw or {}`: an upstream that answers with a JSON array
    # -- a captive portal, a proxy, a changed error envelope -- would otherwise
    # raise AttributeError here, and an exception out of a normaliser is not
    # an UpstreamError, so it escapes the cache and reaches the request
    # handler. The empty-list case passed the old guard only because an empty
    # list is falsy.
    if not isinstance(raw, dict):
        return []
    results = raw.get("results")
    if not isinstance(results, list):
        return []

    quotes = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        # v2 nests under "data"; the legacy path is flat. Read whichever is
        # there, and prefer the nested one when both are.
        values = entry.get("data") if isinstance(entry.get("data"), dict) else entry
        symbol = entry.get("symbol") or entry.get("requestedSymbol")
        price = _number(values.get("regularMarketPrice"))
        if not symbol or price is None:
            continue
        quotes.append({
            "symbol": str(symbol),
            "price": price,
            # A missing change is 0.0, not None: format.js renders a number
            # and would print "null%" for anything else.
            "changePct": _number(values.get("regularMarketChangePercent")) or 0.0,
        })
    return quotes


def _number(value):
    """Pure: `value` as a float, or None if it is not one.

    brapi sends numbers as JSON numbers and the other two providers send them
    as strings, so every provider here converts rather than trusting the type.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load(symbols, token="", get=get_json):
    """fetch + normalise, with upstream failure surfaced as UpstreamError."""
    return normalise(fetch(symbols, token=token, get=get))


__all__ = ["FREE_TIER_SYMBOLS", "QUOTE_URL", "UpstreamError", "fetch", "load", "normalise"]
