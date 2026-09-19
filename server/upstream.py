#!/usr/bin/env python3
"""One outbound HTTP helper, shared by the provider modules.

Standard library only (server/CLAUDE.md), so this is `urllib.request` with
the two things it does not give you by default: a timeout that is always
passed, and JSON decoding with a useful error.

It exists so the four providers do not each carry the same twenty lines of
boilerplate. It is deliberately *not* the seam the tests patch: each provider
keeps its own `fetch`, and TT.2 patches that. Patching here would mean one
test accidentally covering four providers and none of them being pinned to
the URL it actually calls.
"""
import json
import urllib.error
import urllib.request

# Short, because the panel is a display: a provider that has not answered in
# ten seconds has already missed the cycle, and the cached value is a better
# answer than a longer wait. Applied to connect and read together, which is
# what urlopen's timeout means.
TIMEOUT_S = 10


class UpstreamError(Exception):
    """Any failure to get usable JSON from an upstream.

    One exception type on purpose: every caller treats a timeout, a 500, a
    truncated body and a JSON syntax error the same way — serve the last
    good value and flag it stale (T3.3 step 5). The message is for the log.
    """


def get_json(url, headers=None, timeout=TIMEOUT_S):
    """GET `url` and return the decoded JSON.

    Raises UpstreamError, never a urllib or json exception, so callers have
    one thing to catch. The message never contains `headers`, because that is
    where a token would be — see server/CLAUDE.md ("secrets stay here").
    """
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # The body of an error response is often the useful part — brapi says
        # MISSING_TOKEN in it — but it is upstream text of unknown length, so
        # it is truncated rather than logged whole.
        detail = ""
        try:
            detail = exc.read()[:200].decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001 - reading the error body is best effort
            pass
        raise UpstreamError(f"HTTP {exc.code} from {_safe(url)}: {detail}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise UpstreamError(f"cannot reach {_safe(url)}: {exc}") from None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UpstreamError(f"{_safe(url)} did not return JSON: {exc}") from None


def _safe(url):
    """The URL with any query string removed.

    brapi accepts `?token=` as an alternative to the header, and a URL built
    that way would otherwise put the token into every log line and every
    error message this module raises.
    """
    return url.split("?", 1)[0]
