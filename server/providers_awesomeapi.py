#!/usr/bin/env python3
"""FX rates, from AwesomeAPI.

Here rather than in brapi for the same reason as crypto: brapi's currency
endpoint answers `401 MISSING_TOKEN` without a token — measured 2026-09-19,
recorded in providers_brapi.py — and the T3.3 task file named AwesomeAPI as
the key-free replacement.

    GET /json/last/USD-BRL,EUR-BRL

    {"USDBRL": {"code": "USD", "codein": "BRL", "bid": "5.1434",
                "pctChange": "0.36882", ...},
     "EURBRL": {...}}

**A currency pair is spelled three ways in this one file**, and the T3.3 task
file warned about two of them before the third turned up:

    config.json   USD-BRL      the hyphen, as the owner types it
    request path  USD-BRL      the hyphen again, which is AwesomeAPI's own
    response key  USDBRL       no separator at all
    payload       USD/BRL      the slash, which is what the panel renders

`normalise` is where all four meet, and it is the only place any of them is
allowed to appear. Nothing downstream ever sees a hyphen — that is a rule
from the task file, and the reason is that `USD-BRL` rendered on a panel
reads as a subtraction.

**Values are strings**, like Binance's, and `bid` is the one to read: `ask`
is what you would pay, `bid` what you would get, and a panel that shows one
number should show the one every other Brazilian quote source shows.
"""
from server.upstream import UpstreamError, get_json

LAST_URL = "https://economia.awesomeapi.com.br/json/last"


def to_request_pair(configured):
    """Pure: config's `USD-BRL` -> the request spelling, `USD-BRL`.

    An identity today, and named anyway: it is the seam that stops a future
    provider swap from leaking a hyphen into a URL that does not want one.
    Also accepts `USD/BRL` and `USDBRL`, so a config typed either way works.
    """
    text = str(configured).upper().replace("/", "-")
    if "-" not in text and len(text) == 6:
        text = f"{text[:3]}-{text[3:]}"
    return text


def to_display_pair(key):
    """Pure: the response key `USDBRL`, or any spelling, -> `USD/BRL`."""
    text = str(key).upper().replace("-", "").replace("/", "")
    if len(text) == 6:
        return f"{text[:3]}/{text[3:]}"
    return str(key).upper()


def fetch(pairs, get=get_json):
    """Ask AwesomeAPI for `pairs`. The seam TT.2 patches."""
    if not pairs:
        return {}
    requested = ",".join(to_request_pair(pair) for pair in pairs)
    return get(f"{LAST_URL}/{requested}")


def normalise(raw, pairs=None):
    """Pure: AwesomeAPI's response -> `[{pair, rate, changePct}, ...]`.

    `pairs` is the configured order. AwesomeAPI returns a JSON object, and
    while CPython preserves insertion order, the panel's row order should
    follow what the owner wrote in config.json rather than what an upstream
    happened to serialise first. Absent, the response's own order is used.
    """
    if not isinstance(raw, dict):
        return []

    if pairs:
        keys = [to_request_pair(p).replace("-", "") for p in pairs]
        # Anything the upstream returned that was not asked for still gets
        # through, after the configured rows, rather than being dropped
        # silently — an unexpected row is visible, a missing one is not.
        keys += [k for k in raw if k not in keys]
    else:
        keys = list(raw)

    fx = []
    for key in keys:
        entry = raw.get(key)
        if not isinstance(entry, dict):
            continue
        rate = _number(entry.get("bid"))
        if rate is None:
            continue
        fx.append({
            "pair": to_display_pair(key),
            "rate": rate,
            "changePct": _number(entry.get("pctChange")) or 0.0,
        })
    return fx


def _number(value):
    """Pure: `value` as a float, or None. AwesomeAPI sends strings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load(pairs, get=get_json):
    """fetch + normalise, with upstream failure surfaced as UpstreamError."""
    return normalise(fetch(pairs, get=get), pairs=pairs)


__all__ = ["LAST_URL", "UpstreamError", "fetch", "load", "normalise",
           "to_display_pair", "to_request_pair"]
