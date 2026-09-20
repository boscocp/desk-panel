#!/usr/bin/env python3
"""Desk panel PC server.

Standard library only -- see server/CLAUDE.md. This process is the login
signal (invariant 2 in the root CLAUDE.md): it is meant to be launched by a
logged-in user's session and to die with it, never to auto-restart or run as
a service.

The request handler only routes and serialises. All real logic lives in
plain functions (`route`, `load_config`, below, and whatever T3.3+ adds) so
tests can call them directly without a socket -- see server/CLAUDE.md and
TT.2.
"""
import argparse
import functools
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Run two ways, and both are documented. `python -m unittest discover -t .`
# imports this as `server.server`, with the repository root on sys.path; but
# `python server/server.py` -- the command in server/CLAUDE.md and in every
# launcher -- puts `server/` on sys.path and the root nowhere, so the absolute
# imports below would not resolve. Adding the root first costs nothing in the
# package case, where this branch is not taken at all.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import providers_awesomeapi, providers_binance, providers_brapi, providers_openmeteo  # noqa: E402
from server.config_format import ConfigError, format_for_path, merge, parse  # noqa: E402
from server.upstream import UpstreamError  # noqa: E402

HOST = "0.0.0.0"
PORT = 8777
MIN_PYTHON = (3, 11)

SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLE_CONFIG_PATH = SCRIPT_DIR / "config.example.toml"

# The two names the script_dir fallback will answer to, best first. Order is
# the whole rule: config.toml wins wherever both exist (T3.12 step 3).
CONFIG_FILENAMES = ("config.toml", "config.json")

# Every key config.example.toml ships, with a safe empty/inert default.
# `load_config` fills in whatever a real config file omits so that a
# partial file degrades gracefully instead of raising KeyError deep inside
# a handler -- see server/CLAUDE.md ("config drives behaviour").
#
# TT.2 asserts that this dict and the example file carry the same key set,
# in both directions. The example is where the catalogue of legal values
# lives, so a key added here and not there is a key no owner finds out about.
DEFAULT_CONFIG = {
    "port": PORT,
    "brapi_token": "",
    # brapi's free plan refuses a request carrying more than one symbol, so
    # every ticker costs a request. Raise it if the plan does.
    "brapi_symbols_per_request": 1,
    "quotes": [],
    "crypto": [],
    "fx": [],
    "city": "Sao Paulo",
    "timezone": "America/Sao_Paulo",
    # 600, not 300, and the arithmetic is the reason. brapi's free plan allows
    # one symbol per request and 15k requests a month, so three tickers cost
    # three requests a refresh: at 300s that is 25,920 a month against a 15,000
    # budget, and the B3 card would go permanently stale around the 17th. At
    # 600s it is 12,960 with the PC logged in around the clock.
    "quotes_interval_s": 600,
    "weather_interval_s": 900,
    # Daily closes change once a day, so the sparkline's series is fetched on
    # a clock measured in hours rather than minutes. Six is arbitrary and
    # generous: it costs four requests a day across two providers.
    "history_interval_s": 21600,
    "history_days": 30,
    "night_start": "22:00",
    "night_end": "07:00",
    # Which theme renders the panel. Read by T6.7: it rides the /quotes
    # response into the payload, and the page picks the matching
    # web/themes/<name>/ out of the set the APK already carries. Selecting a
    # theme must never need a rebuild, which is the whole reason it is runtime
    # config and not .env (ADR 0013). A name no theme answers to falls back to
    # "neon" in the page, not here: the server has no idea which themes the
    # installed APK was built with, and guessing would turn a cosmetic typo
    # into a blank panel.
    "theme": "neon",
    "actions": {},
}


# ConfigError is defined in config_format, beside the two parsers whose
# exceptions it replaces, and re-exported here because every caller in this
# file and in the tests has always imported it from `server.server`.


def load_config(path):
    """Load the config at `path`, filling missing keys with DEFAULT_CONFIG.

    The format comes from the suffix -- `.toml` is TOML, anything else is
    JSON (`config_format.format_for_path`). Raises ConfigError, never a
    bare exception, for a missing file or a malformed one, so callers get
    one type to handle.

    The single read is the only I/O; the parsing and the merge are pure
    functions in config_format, which is what lets TT.2 cover both formats
    without a filesystem. No logging, and no defaults baked into the
    network layer.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"{path} not found. Copy {EXAMPLE_CONFIG_PATH} to that path "
            f"(the suffix is what picks the parser) and fill in your "
            f"brapi token."
        ) from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None

    return merge(parse(raw, format_for_path(path), name=str(path)), DEFAULT_CONFIG)


def config_search_paths(argv, env, script_dir, exists=None):
    """Pure: ordered config path candidates, highest priority first.

    Order: `--config <path>` (from argv), then `DESK_PANEL_CONFIG` (from
    env), then the script_dir fallback. Only sources that are actually set
    contribute a candidate; the script_dir fallback always does, so the
    list is never empty and the caller can just take the first entry.

    This is what makes config discovery cwd-independent -- a Scheduled Task
    with no working directory starts in C:\\Windows\\System32, where a
    relative "server/config.json" resolves to nothing. All three launchers
    pass an absolute --config, so cwd never matters for them; the
    script_dir fallback is for running the server by hand.

    **The fallback is the only place the two formats can meet**, and that
    is not an accident: the other two sources are handed a path, and a path
    names its own format. So `--config x.json` stays exactly as
    authoritative as it was -- it is never quietly upgraded to a `.toml`
    sitting next to it, and a launcher pointing at a file that has been
    deleted still fails loudly instead of starting on somebody else's
    config.

    Among the fallback's two names, `config.toml` wins; `config.json` is
    chosen only when it is there and the .toml is not, which is T3.12 step
    3 -- nobody's running panel may break because a file was renamed. With
    neither present the candidate is `config.toml`, so the "not found"
    message names the file the owner should write rather than the one being
    retired.

    `exists` is injected rather than read, which is what keeps this pure:
    main passes `os.path.exists`, a test passes a set's `__contains__`, and
    None means "nothing is there" -- the answer is then always the .toml.
    """
    paths = []
    argv = list(argv) if argv is not None else []
    config_arg = None
    for i, token in enumerate(argv):
        if token == "--config" and i + 1 < len(argv):
            config_arg = argv[i + 1]
        elif token.startswith("--config="):
            config_arg = token.split("=", 1)[1]
    if config_arg is not None:
        paths.append(Path(config_arg))

    env_val = (env or {}).get("DESK_PANEL_CONFIG")
    if env_val:
        paths.append(Path(env_val))

    paths.append(_fallback_config_path(script_dir, exists))
    return paths


def _fallback_config_path(script_dir, exists=None):
    """Pure given `exists`: which of CONFIG_FILENAMES the script_dir
    fallback names. First one that exists wins; failing that, the first
    name in the tuple. See config_search_paths for why only this source
    gets a choice.
    """
    candidates = [Path(script_dir) / name for name in CONFIG_FILENAMES]
    if exists is not None:
        for candidate in candidates:
            if exists(candidate):
                return candidate
    return candidates[0]


def legacy_format_notice(path, explicit=False, example_path=None):
    """Pure: one line pointing a JSON config at its TOML replacement, else
    None.

    Not a deprecation and not a warning. `config.json` is still read and
    still entirely correct (T3.12 step 3); what it cannot do is carry
    comments, which means it cannot tell its owner which tickers answer
    without a token or how an FX pair is spelled. That catalogue is the
    actual deliverable of this change, and an owner who is never told the
    file exists never gets it.

    **`explicit` changes the advice, and getting it wrong would be worse
    than saying nothing.** A path that came from `--config` or
    `DESK_PANEL_CONFIG` is never upgraded to a neighbouring `.toml` -- see
    config_search_paths, which is deliberate -- and every installed
    launcher passes one: `install_task.ps1` bakes an absolute
    `--config ...\\config.json` into the Scheduled Task. So the fallback's
    advice, "copy the example to config.toml", is a silent no-op there. The
    owner would move their tickers and their token into a file nothing
    reads, restart, and see the old panel with nothing to explain it.
    Whoever passes the path has to change the path.

    Silent for the committed example. `config.example.json` is what T3.11's
    acceptance loads on every run, and a line nagging about a file nobody
    edited is how people learn to skim the output -- the same argument
    config_permission_warning makes about the mode bits on that same file.
    """
    path = Path(path)
    if format_for_path(path) != "json":
        return None
    if path.name.startswith("config.example"):
        return None
    example = EXAMPLE_CONFIG_PATH if example_path is None else example_path
    head = (
        f"notice: {path} is the older JSON config; it still works. The TOML "
        f"replacement is commented -- it names every key, its default, and "
        f"which tickers, pairs and coins actually answer."
    )
    if explicit:
        return (
            f"{head} Moving to it means changing the --config this server was "
            f"started with, not just adding a file: copy {example} beside the "
            f"old one, then re-run your launcher's installer "
            f"(server/install_task.ps1 on Windows) so it points at the new path."
        )
    return f"{head} Copy {example} to {path.with_name('config.toml')} when convenient."


def config_permission_warning(mode, platform, path=None, token=""):
    """Pure: a human-readable warning if `mode` (an os.stat().st_mode
    value) grants group or other permissions on a file that holds a token,
    else None.

    POSIX only -- `st_mode` is meaningless on Windows, where the real
    access control is the NTFS ACL, not a chmod bit. `platform` is whatever
    the caller passes as sys.platform, so this stays pure and testable
    without touching a filesystem.

    `token` gates the warning, because there is nothing to protect without
    one. config.example.json is committed, carries `brapi_token: ""`, and is
    0644 on purpose; warning about it fires on every --check-only run in the
    acceptance suite and names a file the user never edited. A warning that
    cries wolf on the example file is how people learn to ignore the one
    that fires on the real config.

    `path` names the file actually checked, rather than assuming it was
    config.json -- the old message said "config.json" while inspecting
    whatever --config pointed at.

    Always a warning, never a reason to refuse to start: this process is
    the login signal (invariant 2), and dying over a permission bit breaks
    that harder than a loose mode bit on a LAN-only box risks.
    """
    if platform == "win32":
        return None
    if not token:
        return None
    if mode & 0o077:
        name = path if path is not None else "config.json"
        return (
            f"warning: {name} is readable by group/other (mode "
            f"{oct(mode & 0o777)}); it holds the brapi token. Consider: "
            f"chmod 600 {name}"
        )
    return None


def check_python_version(version_info=None):
    """Pure: a readable error message if `version_info` is older than
    MIN_PYTHON, else None. Defaults to the running interpreter's own
    version. Guarding this explicitly matters because a too-old
    interpreter otherwise fails deep inside stdlib with a traceback that
    looks like a restart loop in journald or launchd, not a version
    mismatch.
    """
    if version_info is None:
        version_info = sys.version_info
    if tuple(version_info[:2]) < MIN_PYTHON:
        return (
            f"desk-panel server requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} "
            f"or newer (found {version_info[0]}.{version_info[1]})."
        )
    return None


class TimedCache:
    """One cached value, its age, and the last good copy of it.

    Two jobs, and the second is the one that matters on a desk. It keeps the
    panel off the upstreams between refreshes -- brapi's free tier is 15k
    requests a month and a 2s poll would burn it in days (T3.3 step 4). And
    when a refresh fails it serves the previous value with `stale` set,
    because a slightly old price beats an empty panel (T3.3 step 5).

    The clock is passed in rather than read, so TT.2 can move time without
    sleeping.
    """

    def __init__(self):
        self.value = None
        self.fetched_at = None
        self.stale = False
        self.last_error = None
        # Requests are served on threads (see Server below), so two polls
        # arriving together must not both start the same refresh -- that would
        # double the outbound traffic at exactly the moment the TTL expires.
        # The lock is held across the fetch; the second caller waits and then
        # finds the value fresh.
        self._lock = threading.Lock()

    def fresh_at(self, now, ttl_s):
        """Pure: whether the last *attempt* was within `ttl_s` of `now`.

        The attempt, not the value. Requiring a non-None value here meant a
        cold start whose first fetch failed was never fresh, so every request
        after it tried again -- precisely the hammering this class exists to
        prevent. It survived the warm-path test because that test had a value
        to hold. A PC that boots before its router does is all it takes.
        """
        return self.fetched_at is not None and now - self.fetched_at < ttl_s

    def get(self, now, ttl_s, produce):
        """The cached value, refreshing through `produce` when it has aged out.

        Returns `(value, stale)`. `stale` is True whenever the value on hand
        is not the result of a successful call -- either an older one kept
        after a failure, or nothing at all on a cold start that failed.
        """
        if self.fresh_at(now, ttl_s):
            return self.value, self.stale

        with self._lock:
            # Re-checked under the lock: whoever held it may have just
            # refreshed, and a second fetch would be pure waste.
            if self.fresh_at(now, ttl_s):
                return self.value, self.stale

            try:
                self.value = produce()
                self.fetched_at = now
                self.stale = False
                self.last_error = None
            except UpstreamError as exc:
                # Deliberately not re-raised: every caller would turn it into
                # the same thing, and the last good value is a better answer
                # than an error page on a panel nobody is sitting at.
                #
                # `fetched_at` moves on a failure too, so the contract is
                # simply "at most one upstream attempt per TTL", success or
                # failure, warm or cold. The alternative -- leaving it behind
                # so the next request retries -- looks like resilience and is
                # the opposite: an upstream that is down becomes one outbound
                # request per panel poll, which is the traffic this cache
                # exists to prevent, arriving exactly when the upstream can
                # least afford it. The cost is that recovery waits out a TTL,
                # which the `stale` flag makes visible.
                self.last_error = str(exc)
                self.stale = True
                self.fetched_at = now
            return self.value, self.stale


class App:
    """Config, caches and providers -- everything `route` needs and the
    request handler must not know about.

    Holding it in one object is what keeps `route` callable from a test with
    a hand-built stub, which is the rule in server/CLAUDE.md: the handler
    routes and serialises, and nothing else lives in the socket layer.
    """

    def __init__(self, config, clock=time.monotonic):
        self.config = config
        self.clock = clock
        # One cache per market, not one for the three together. They come from
        # three unrelated upstreams, and sharing a cache meant the first one to
        # fail took the other two down with it: a brapi 401 over a ticker that
        # needs a token emptied FX and crypto as well, and the panel went
        # blank while both of those upstreams were answering perfectly. A
        # failure should cost its own market and nothing else.
        self.market_caches = {
            "quotes": TimedCache(),
            "fx": TimedCache(),
            "crypto": TimedCache(),
        }
        self.weather_cache = TimedCache()
        # Its own clock, and a much slower one: the series is daily closes,
        # which do not move between refreshes of the prices beside them.
        self.history_caches = {
            "quotes": TimedCache(),
            "fx": TimedCache(),
            "crypto": TimedCache(),
        }
        self._history_lock = threading.Lock()
        self._history_refreshing = set()
        # Coordinates never change, so the geocode is cached for the life of
        # the process rather than on a TTL (T3.4 step 1).
        self.coords = None

    def quotes(self):
        """`{quotes, fx, crypto, stale}` -- the three markets in one payload.

        Fetched and cached independently, then assembled. `stale` is true if
        any of the three is, because the badge means "something here is older
        than it looks" and that is true if it is true of any part -- but a
        market that is answering keeps its rows either way.
        """
        config = self.config
        ttl = config.get("quotes_interval_s", 300)
        now = self.clock()

        producers = {
            "quotes": lambda: providers_brapi.load(
                config.get("quotes", []),
                token=config.get("brapi_token", ""),
                per_request=config.get("brapi_symbols_per_request", 1),
            ),
            "fx": lambda: providers_awesomeapi.load(config.get("fx", [])),
            "crypto": lambda: providers_binance.load(config.get("crypto", [])),
        }

        history = self._history(now)

        wanted = {"quotes": len(config.get("quotes", [])),
                  "fx": len(config.get("fx", [])),
                  "crypto": len(config.get("crypto", []))}

        payload = {}
        stale = False
        for market, produce in producers.items():
            rows, market_stale = self.market_caches[market].get(now, ttl, produce)
            rows = rows if rows is not None else []

            # Before the partial-market check below, which reads it. Assigned
            # after it, this was unbound on the first market and held the
            # *previous* market's key on the rest -- a crash on one path and a
            # silently wrong answer on the other.
            key = key_for(market)

            # Fewer rows than were asked for is a failure the cache cannot see.
            # brapi sends one symbol per request now, so a 429 on one ticker
            # returns the other two and looks like a success: that row would
            # vanish from the panel for a whole TTL with nothing marked. A
            # rate-limited request is not a delisted ticker, and the badge is
            # how the panel says "something here is missing".
            if len(rows) < wanted.get(market, 0):
                market_stale = True
                # Named, not just counted. A partial market used to be
                # completely silent: the row vanished, the cache recorded a
                # success, and the only evidence was a gap on the panel. Seen
                # on this desk when three brapi quote calls raced three
                # history calls, which the per-symbol split and the background
                # refresh made possible at the same moment.
                # Separators stripped on both sides before comparing: config
                # spells an FX pair USD-BRL and the row spells it USD/BRL, so
                # a literal comparison would report every pair as missing
                # whenever any one of them was.
                got = {_bare(r.get(key, "")) for r in rows}
                missing = sorted(str(x) for x in config.get(market, [])
                                 if _bare(x) not in got)
                print(f"{market}: {len(rows)} of {wanted[market]} rows"
                      + (f", missing {', '.join(missing)}" if missing else ""),
                      file=sys.stderr)

            # Attached rather than merged into the cache, so a history that
            # failed or has not been fetched yet costs the row its picture and
            # nothing else. An absent series is an absent key: the page draws
            # no line rather than a line through no data.
            payload[market] = [
                dict(row, history=history.get(market, {}).get(row.get(key), []))
                for row in rows
            ]
            stale = stale or market_stale
        payload["stale"] = stale
        # Not a market fact, and it rides here anyway: /quotes and /weather are
        # the only two things the phone asks for, DataPoller merges them into
        # the one payload the page gets, and a third endpoint would be a third
        # request per cycle for a string that changes when a human edits a file.
        # /quotes rather than /weather because /quotes is already the payload's
        # carrier -- it is where `stale` is decided for the whole panel.
        payload["theme"] = config.get("theme", "")
        return payload

    def _history(self, now):
        """`{market: {symbol: [values]}}`, refreshed off the request path.

        Never marks the payload stale, and never makes anybody wait for it. A
        sparkline is a decoration on a row that already carries the number it
        decorates, so it must not be able to call that number old and it must
        not be able to delay it either: one cache miss here is up to six
        sequential upstream calls, each with a ten second timeout, against a
        phone that gives the whole request five seconds (DataPoller). Blocking
        would mean a failed poll on every history cycle.

        So a stale history refreshes in the background and the request serves
        whatever is on hand, which on a cold start is nothing at all -- the
        panel draws no lines for one cycle and then has them.
        """
        history = {}
        for market, cache in self.history_caches.items():
            if not cache.fresh_at(now, self._history_ttl(market)):
                self._refresh_history_async(market)
            history[market] = cache.value or {}
        return history

    def _history_ttl(self, market):
        """Six hours once every row has a line, minutes while any is missing.

        Daily closes do not move between refreshes, so the long TTL is right
        for a complete answer. It is wrong for an incomplete one, and
        incomplete is what a blip during the refresh leaves behind -- one
        badly timed failure would otherwise cost a ticker its sparkline for
        six hours, with no retry and nothing to say why. Seen on this desk:
        SEER3 came back with zero points while the other six rows were fine.

        Counting rather than checking for emptiness, because the partial case
        is the common one: a total failure is a network outage, a single
        missing symbol is an ordinary rate limit.
        """
        long_ttl = self.config.get("history_interval_s", 21600)
        series = self.history_caches[market].value or {}
        if len(series) >= len(self.config.get(market, [])):
            return long_ttl
        return min(long_ttl, self.config.get("quotes_interval_s", 600))

    def _refresh_history_async(self, market):
        """Start one background refresh for `market`, or leave the running one
        alone. TimedCache's own lock would serialise callers rather than
        letting them through, which is the opposite of what is wanted here."""
        with self._history_lock:
            if market in self._history_refreshing:
                return
            self._history_refreshing.add(market)

        def run():
            try:
                self.history_caches[market].get(
                    self.clock(), self._history_ttl(market),
                    self._history_producer(market))
            finally:
                with self._history_lock:
                    self._history_refreshing.discard(market)

        thread = threading.Thread(target=run, name=f"history-{market}", daemon=True)
        thread.start()

    def _history_producer(self, market):
        config = self.config
        days = config.get("history_days", 30)
        if market == "quotes":
            # Needs the token, like the prices beside it. Without one this
            # returns nothing and the B3 rows simply have no line.
            return lambda: providers_brapi.load_history(
                config.get("quotes", []), token=config.get("brapi_token", ""), days=days
            )
        if market == "fx":
            return lambda: providers_awesomeapi.load_history(config.get("fx", []), days)
        return lambda: providers_binance.load_history(config.get("crypto", []), days)

    def warm_history(self):
        """Start fetching every series now, rather than on the first request.

        Without it the panel's first payload after a login carries no history
        at all -- the refresh is deliberately off the request path, so the
        first poll is served before it finishes -- and every card would be
        drawn without its lines for a cycle at exactly the moment somebody has
        just sat down. Called once at startup; costs nothing if the phone is
        not there, because the server only runs while somebody is logged in.
        """
        for market in self.history_caches:
            self._refresh_history_async(market)

    def weather(self):
        """`{tempC, minC, maxC, code, city, stale}` for the configured city."""
        config = self.config
        ttl = config.get("weather_interval_s", 900)

        def produce():
            # Geocode first and keep the answer immediately. Folding both calls
            # into one meant a forecast outage threw away coordinates that had
            # just been resolved successfully, so every later refresh
            # re-geocoded -- doubling the requests against a 10k/day budget
            # exactly while the provider was already struggling. A city does
            # not move; once located it stays located.
            if self.coords is None:
                located = providers_openmeteo.normalise_geocode(
                    providers_openmeteo.fetch_geocode(config.get("city", "")))
                if located is None:
                    raise UpstreamError(
                        f"no coordinates found for city {config.get('city', '')!r}")
                self.coords = located
            raw = providers_openmeteo.fetch_forecast(
                self.coords["lat"], self.coords["lon"], config.get("timezone", ""))
            return providers_openmeteo.normalise(
                raw, city=self.coords.get("city") or config.get("city", ""))

        value, stale = self.weather_cache.get(self.clock(), ttl, produce)
        payload = dict(value or {
            "tempC": None, "minC": None, "maxC": None,
            "code": None, "city": config.get("city", ""),
        })
        payload["stale"] = stale
        return payload


def _bare(symbol):
    """Pure: a symbol or pair reduced to letters and digits, upper case.

    The one place the project's several spellings of the same thing have to be
    compared rather than converted -- see providers_awesomeapi for the full
    list of them.
    """
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())


def key_for(market):
    """Pure: which field identifies a row in `market`.

    FX rows are keyed by `pair` and the other two by `symbol`, which is a
    difference the payload contract makes and this is the one place that has
    to know it.
    """
    return "pair" if market == "fx" else "symbol"


def action_id(path):
    """Pure: the id in `/action/<id>`, or None if `path` is not that shape.

    One segment, non-empty, no nesting. The id is not used for anything yet
    (T3.7 returns 501), and when it is it will be looked up in a closed
    allowlist from config -- never turned into a command, a path or an
    argument. Matching narrowly here is the first half of that promise.
    """
    prefix = "/action/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    if not rest or "/" in rest or "?" in rest:
        return None
    return rest


def route(method, path, app=None):
    """Pure routing: (method, path) -> (status, body_bytes, content_type).

    No I/O of its own -- callable directly from tests without starting a
    server. `app` supplies the data routes; without one they answer 503
    rather than pretending, which is what lets the existing two-argument
    tests keep asserting that /ping and 404 need no state at all.
    """
    if method == "GET" and path == "/ping":
        return _json(200, {"ok": True})

    if method == "GET" and path == "/quotes":
        if app is None:
            return _json(503, {"error": "not configured"})
        return _json(200, app.quotes())

    if method == "GET" and path == "/weather":
        if app is None:
            return _json(503, {"error": "not configured"})
        return _json(200, app.weather())

    if method == "POST" and action_id(path) is not None:
        # T3.7: the v2 placeholder. 501 is "not implemented", which is
        # exactly what this is -- 404 would say the route does not exist and
        # 200 would say something happened.
        return _json(501, {"error": "not implemented"})

    return 404, b"", "text/plain"


def _json(status, payload):
    """(status, body, content_type) for a JSON response."""
    return status, json.dumps(payload).encode("utf-8"), "application/json"


class Handler(BaseHTTPRequestHandler):
    """Dumb by design: routes to `route()` and serialises its result."""

    def __init__(self, *args, app=None, **kwargs):
        # Before super().__init__, which handles the whole request before it
        # returns -- anything set afterwards would not exist yet when
        # do_GET runs.
        self.app = app
        super().__init__(*args, **kwargs)

    def _handle(self, method):
        try:
            status, body, content_type = route(method, self.path, getattr(self, "app", None))
        except Exception:  # noqa: BLE001 - deliberately everything
            # route() used to be pure; it does I/O now, and TimedCache
            # re-raises anything that is not an UpstreamError on purpose --
            # a bug in a normaliser must not be laundered into "stale".
            # Without this guard socketserver prints the traceback and closes
            # the socket with no status line, so the phone sees an IOException
            # and the operator sees nothing. A 500 is a failure somebody can
            # read; a reset connection is one they have to guess at.
            traceback.print_exc()
            status, body, content_type = _json(500, {"error": "internal error"})
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def _allow_reuse_address(os_name):
    """Pure: whether SO_REUSEADDR should be on for `os_name` (an os.name
    value). Split out from the Server class body so TT.2 can test both
    branches without reloading this module under a patched os.name --
    that reload would itself explode, since the module-level
    `Path(__file__).resolve()` above picks WindowsPath/PosixPath from the
    live os.name at import time.
    """
    return os_name != "nt"


class Server(ThreadingHTTPServer):
    """A threading HTTP server with a platform-correct `allow_reuse_address`.

    **Threading is not a performance choice; it protects invariant 2.** This
    process is the login signal, and `/ping` answering is the whole of that
    signal. Serving one request at a time meant a `/quotes` whose cache had
    just expired could sit inside three sequential upstream calls -- up to 30s
    of `urlopen` timeouts -- with `/ping` queued behind it. The phone gives a
    ping 1500ms and `PcState` flips to OFFLINE on a single failure, so the
    panel would go dark while its owner sat at the logged-in PC. An internet
    hiccup would have looked exactly like a logout, which is the one thing
    this server must never get wrong.

    `TimedCache` takes a lock around its refresh, so concurrent requests share
    one outbound fetch rather than starting several.

    On POSIX, SO_REUSEADDR just lets a restart rebind during TIME_WAIT --
    harmless, and http.server sets it to 1 by default. On Windows the same
    flag lets a *second* process bind the same port and steal connections,
    which is not a restart, it's fast user switching silently running two
    servers with nondeterministic answers. So on Windows we want the
    default socket behaviour (refuse, EADDRINUSE) instead of stdlib's 1.
    """

    allow_reuse_address = _allow_reuse_address(os.name)

    # Nothing here should outlive the session this process belongs to
    # (invariant 2): a request thread still blocked on a slow upstream must
    # not keep the interpreter alive after the desktop has gone.
    daemon_threads = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Desk panel PC server.")
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "path to config.toml or config.json; the suffix picks the parser "
            "(see config_search_paths for the discovery order)"
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="load and validate config, print the result, and exit without binding a socket",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="append stdout/stderr here instead (Windows installer only, pythonw has no console)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    raw_argv = sys.argv[1:] if argv is None else list(argv)

    version_error = check_python_version()
    if version_error:
        print(version_error, file=sys.stderr)
        sys.exit(1)

    args = parse_args(raw_argv)

    if args.log_file:
        # pythonw has no console, and Task Scheduler cannot redirect stdout
        # without spawning `cmd /c`, which flashes a window -- so the
        # Windows installer points this at a file instead.
        log_fh = open(Path(args.log_file), "a", encoding="utf-8", buffering=1)
        sys.stdout = log_fh
        sys.stderr = log_fh
    else:
        # Explicit UTF-8 and line buffering: Windows does not default
        # stdout/stderr to UTF-8, and journald/launchd want output flushed
        # promptly rather than block-buffered.
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            try:
                stream.reconfigure(encoding="utf-8", line_buffering=True, write_through=True)
            except (AttributeError, ValueError):
                pass

    config_candidates = config_search_paths(
        raw_argv, os.environ, SCRIPT_DIR, exists=os.path.exists
    )
    config_path = config_candidates[0]
    # The script_dir fallback is always appended last and is the only entry
    # present unconditionally, so more than one candidate means --config or
    # DESK_PANEL_CONFIG won -- and a path someone passed can only be changed
    # by whoever passes it. legacy_format_notice says why that matters.
    config_is_explicit = len(config_candidates) > 1

    # A server that starts with silently-empty config looks healthy and
    # shows an empty panel -- worse than one that refuses to start with a
    # clear message. So this is fatal, not a fallback to DEFAULT_CONFIG.
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    if os.name != "nt":
        try:
            mode = os.stat(config_path).st_mode
        except OSError:
            mode = None
        if mode is not None:
            warning = config_permission_warning(
                mode, sys.platform, path=config_path, token=config.get("brapi_token", "")
            )
            if warning:
                print(warning, file=sys.stderr)

    notice = legacy_format_notice(config_path, explicit=config_is_explicit)
    if notice:
        print(notice, file=sys.stderr)

    if args.check_only:
        print(f"config OK: {config_path}")
        return

    port = config.get("port", PORT)
    # functools.partial rather than a class attribute: the app is per-server
    # state, and a class attribute would be shared by every server in a test
    # process that starts more than one.
    app = App(config)
    # Before the socket is bound rather than after: the first poll lands within
    # seconds of a login, and the series should already be on its way.
    app.warm_history()
    server = Server((HOST, port), functools.partial(Handler, app=app))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
