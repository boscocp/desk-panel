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


# How many symbols may ride in one request. **One, because that is what
# brapi's free plan allows**, and asking for more is not a partial success --
# the whole request is refused:
#
#   HTTP 400 QUOTES_PER_REQUEST
#   "Seu plano permite no máximo 1 ativo(s) por requisição. Você enviou 3."
#
# Measured 2026-09-19, with a real token, after the three symbols had each
# answered individually. It is the same shape of trap as the free-tier ticker
# list: a card that renders nothing, and an explanation that exists only in a
# response body nobody reads. Paid plans raise the limit, so this is config
# rather than a constant.
DEFAULT_SYMBOLS_PER_REQUEST = 1


def fetch(symbols, token="", get=get_json):
    """Ask brapi for `symbols` in one request. The seam TT.2 patches.

    Callers should go through `load`, which respects the per-request limit;
    this stays single-request so a test can assert exactly one URL.

    `get` is injected rather than imported at the call site so a test can
    replace exactly this module's outbound call — see server/CLAUDE.md.
    """
    if not symbols:
        return {"results": []}
    url = f"{QUOTE_URL}?symbols={','.join(symbols)}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return get(url, headers=headers)


def chunks(symbols, size):
    """Pure: `symbols` split into lists of at most `size`, size floored at 1."""
    size = max(1, int(size))
    return [list(symbols[i:i + size]) for i in range(0, len(symbols), size)]


# Historical closes come from the *legacy* path with a range, not from
# /api/v2/stocks/quote -- measured 2026-09-19: the v2 endpoint accepts the
# range parameters and returns no historicalDataPrice at all, silently. The
# legacy one returns 21 daily points for range=1mo.
HISTORY_URL = "https://brapi.dev/api/quote"


def range_for(days):
    """Pure: a day count -> the nearest range brapi accepts.

    brapi takes named ranges, not a number, so `history_days` has to be mapped
    rather than passed. Rounding up keeps the sparkline at least as long as
    asked for; the other two providers take a count directly and get exactly
    what config says.
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    for limit, name in ((5, "5d"), (30, "1mo"), (90, "3mo"), (180, "6mo"), (365, "1y")):
        if days <= limit:
            return name
    return "5y"


def fetch_history(symbol, token="", get=get_json, days=30, interval="1d"):
    """One symbol's daily closes. The seam TT.2 patches.

    One per call, like `fetch`, because the free plan's one-asset-per-request
    limit applies here too.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return get(f"{HISTORY_URL}/{symbol}?range={range_for(days)}&interval={interval}",
               headers=headers)


def normalise_history(raw):
    """Pure: the historical response -> `[close, ...]`, oldest first.

    brapi returns the points ascending by date, so this sorts on `date`
    anyway rather than trusting it: the two other providers in this project
    disagree with each other about direction, and a series drawn backwards is
    a rise rendered as a fall with nothing to say so.
    """
    if not isinstance(raw, dict):
        return []
    results = raw.get("results")
    if not isinstance(results, list) or not results:
        return []
    entry = results[0]
    if not isinstance(entry, dict):
        return []
    points = entry.get("historicalDataPrice")
    if not isinstance(points, list):
        return []

    dated = []
    for point in points:
        if not isinstance(point, dict):
            continue
        close = _number(point.get("close"))
        when = _number(point.get("date"))
        if close is not None:
            dated.append((when if when is not None else 0.0, close))
    dated.sort(key=lambda pair: pair[0])
    return [close for _, close in dated]


def load_history(symbols, token="", get=get_json, days=30):
    """`{symbol: [closes oldest-first]}` for every symbol that answered.

    A symbol whose history fails is simply absent: a missing sparkline costs
    that row its picture and never its price. But a run where *every* symbol
    failed raises, so the cache records it and retries rather than storing
    emptiness for six hours with nothing to say why.

    Keyed by the upstream's spelling, upper-cased, because that is how the
    price rows are keyed -- a lowercase ticker in config.json would otherwise
    silently lose its line.
    """
    symbols = list(symbols or [])
    history = {}
    failures = []
    for symbol in symbols:
        try:
            series = normalise_history(fetch_history(symbol, token=token, get=get, days=days))
        except UpstreamError as exc:
            failures.append(exc)
            continue
        if series:
            history[str(symbol).upper()] = series

    if symbols and failures and not history:
        raise failures[0]
    return history


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


def load(symbols, token="", get=get_json, per_request=DEFAULT_SYMBOLS_PER_REQUEST):
    """Every symbol, in as few requests as the plan allows, normalised.

    A chunk that fails costs its own symbols and no more — the same rule
    `normalise` already applies to a single delisted ticker. Only a run where
    *every* chunk failed raises, because that is the case where the card has
    nothing to show and the panel should say stale rather than empty-and-fine.
    """
    symbols = list(symbols or [])
    if not symbols:
        return []

    rows = []
    failures = []
    for group in chunks(symbols, per_request):
        try:
            rows.extend(normalise(fetch(group, token=token, get=get)))
        except UpstreamError as exc:
            failures.append(exc)

    if failures and not rows:
        raise failures[0]
    return rows


__all__ = ["DEFAULT_SYMBOLS_PER_REQUEST", "FREE_TIER_SYMBOLS", "QUOTE_URL",
           "HISTORY_URL", "UpstreamError", "chunks", "fetch", "fetch_history", "load",
           "range_for",
           "load_history", "normalise", "normalise_history"]
