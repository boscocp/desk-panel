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
import datetime
import functools
import html
import ipaddress
import json
import os
import re
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

from server import display as display_module  # noqa: E402
from server import (market_hours, oauth, providers_awesomeapi,  # noqa: E402
                    providers_binance, providers_brapi, providers_calendar,
                    providers_openmeteo, providers_usno)
from server import actions as actions_module  # noqa: E402
from server import private  # noqa: E402
from server import spectrum as spectrum_module  # noqa: E402
from server.config_format import ConfigError, format_for_path, merge, parse  # noqa: E402
from server.upstream import UpstreamError  # noqa: E402

HOST = "0.0.0.0"
PORT = 8777
MIN_PYTHON = (3, 11)

SCRIPT_DIR = Path(__file__).resolve().parent
EXAMPLE_CONFIG_PATH = SCRIPT_DIR / "config.example.toml"

# Where `make apk` and `assembleRelease` leave their output. Not a config key:
# it is a property of the checkout, not of the panel, and config.example.toml
# is a catalogue of what the panel shows.
APK_DIR = SCRIPT_DIR.parent / "out"

# Without this exact type Chrome on Android saves the file instead of offering
# to install it, which is the whole point of the route.
APK_CONTENT_TYPE = "application/vnd.android.package-archive"

# The name build.gradle.kts renames the release APK to. It is preferred over
# every other APK in out/ and the reason is not tidiness: the phone carries a
# release-signed build, a debug-signed one fails to install over it with
# INSTALL_FAILED_UPDATE_INCOMPATIBLE, and the only way out is an uninstall --
# which throws away MIUI's autostart and battery grants, and those are manual
# per-device toggles that need somebody standing at the phone. See
# android/app/build.gradle.kts and docs/INSTALL-PHONE.md.
RELEASE_APK_NAME = "desk-panel-release.apk"

# A Content-Disposition filename goes into a header unescaped, so anything that
# is not this shape is replaced rather than quoted. A file in out/ is build
# output, but it is also whatever anybody drops there.
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]+$")

# Where the calendar refresh tokens live: beside the config file that names
# the accounts, never inside it. The server writes this file -- Microsoft
# rotates its refresh token on every use -- and a server that rewrote the
# hand-edited config.toml would destroy its comments (ADR 0017).
TOKENS_FILENAME = "calendar-tokens.json"

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
    # Optional, as a pair: where the forecast is read, overriding the geocode
    # of `city`. None here means "geocode the city", as it always did; TOML
    # has no null, so a config that wants that omits both keys.
    "latitude": None,
    "longitude": None,
    # 600, not 300, and the arithmetic is the reason. brapi's free plan allows
    # one symbol per request and 15k requests a month, so three tickers cost
    # three requests a refresh: at 300s that is 25,920 a month against a 15,000
    # budget, and the B3 card would go permanently stale around the 17th. At
    # 600s it is 12,960 with the PC logged in around the clock. Both with
    # `b3_hours` off; see config.example.toml for what the gate saves.
    "quotes_interval_s": 600,
    "weather_interval_s": 900,
    # The moon: the slowest thing on the panel. See config.example.toml.
    "moon_interval_s": 21600,
    # Daily closes change once a day, so the sparkline's series is fetched on
    # a clock measured in hours rather than minutes. Six is arbitrary and
    # generous: it costs four requests a day across two providers.
    "history_interval_s": 21600,
    "history_days": 30,
    # When brapi can have a new B3 price. "auto" follows the exchange's two
    # seasons -- it moves its close with US daylight saving -- plus brapi's
    # delay; see market_hours.py. Outside it brapi's quotes and history are
    # held, unless the answer on hand is incomplete, stale or older than the
    # last close.
    "b3_hours": "auto",
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
    # Which language the panel speaks (T6.11). Runtime config for the same
    # reason `theme` is: changing what a person reads must never mean
    # rebuilding the APK (ADR 0013). "pt-BR" and "en" ship; anything else
    # falls back in the page, not here, because the server has no idea which
    # languages the installed APK was built with and guessing would turn a
    # typo into a panel nobody can read.
    "language": "pt-BR",
    # A list of ids from `actions.CATALOGUE`, never commands. Empty is the
    # right default and the right setting on a network the owner does not
    # control -- see ADR 0015.
    "actions": [],
    # Whether the panel also sleeps while this PC's display is off, and not
    # only while nobody is logged in (T4.6, ADR 0020). On by default: it is
    # what the owner asked for, and a platform the server cannot read answers
    # "unknown", which leaves the panel following the login alone.
    "follow_display": True,
    # The spectrum bars over the buttons (T8.5, ADR 0021): what this PC is
    # playing, streamed on /spectrum. Off by default, because turning it on
    # means capturing the system's audio (macOS asks once); macOS only so far.
    "spectrum": False,
    # The meeting alerts on the AGENDA card (T9.5): a visual cue this many
    # minutes before a meeting, a soft chime this many before it, at this
    # volume. 0 turns either off. See config.example.toml.
    "agenda_soon_min": 5,
    "agenda_chime_min": 1,
    "agenda_chime_volume": 0.4,
    # The panel's traffic, private on the LAN (T9.4, ADR 0018). All three of
    # panel_key, tls_cert and tls_key, or none; none is the server as it was,
    # open to anyone on the network, and `main` says so at every start.
    "panel_key": "",
    "tls_cert": "",
    "tls_key": "",
    "tls_port": private.TLS_PORT,
    # Whether `/app` hands out the APK. Off: once the APK carries panel_key,
    # whoever downloads it has the key (ADR 0018).
    "serve_apk": False,
    # The owner's calendars (T9.1, ADR 0017). Empty is the default and costs
    # nothing: no account, no request, and the AGENDA card stays reserved.
    "calendar_accounts": [],
    "google_client_id": "",
    "google_client_secret": "",
    "microsoft_client_id": "",
    # Five minutes. A calendar changes rarely, both APIs have quotas, and the
    # countdown is re-drawn on the phone every minute from the instant it
    # already holds, which costs no request at all.
    "calendar_interval_s": 300,
    "calendar_lookahead_h": 24,
    # True by the owner's decision, with the cost stated in ADR 0017 and in
    # the example file: anyone on the Wi-Fi can read the titles.
    "calendar_show_titles": True,
    # Names, besides IP literals and localhost, that the Host header may
    # carry. Anything else is a 421 before any route runs: it is what a DNS
    # rebinding attack looks like (ADR 0017).
    "allowed_hosts": [],
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


def tokens_path_for(config_path):
    """Pure: the calendar token file that goes with `config_path`.

    Beside the config, because the config names the accounts and the two are
    a pair: a `--config` pointing elsewhere must not read another setup's
    tokens out of `server/`. `calendar_login.py` resolves it the same way.
    """
    return Path(config_path).with_name(TOKENS_FILENAME)


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

    def __init__(self, config, clock=time.monotonic, tokens_path=None,
                 wall_clock=None, oauth_post=oauth.post_form, display=None,
                 spectrum=None):
        self.config = config
        # The spectrum hub (T8.5), or None when `spectrum` is off or this
        # platform has no capture. Injected like `display`: the real one
        # starts a process, and a test constructing an App must not.
        self.spectrum = spectrum
        # Whether this session's display is on (T4.6, ADR 0020). Injected,
        # not built here: on Windows the reader is a thread with a window of
        # its own, and a test constructing an App must not start one. `main`
        # passes the platform's reader; everything else gets "unknown", which
        # the phone reads as "follow the login alone".
        self.display = display or display_module.Fixed()
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
        # Its own cache and its own interval. The moon's phase is the slowest
        # thing on this panel -- the lit fraction moves about three points a
        # day -- and the USNO's answer is a table of instants that does not
        # change at all between them. Six hours is four requests a day against
        # an endpoint with no quota published, and a stale answer here is
        # invisible: nobody can see three points of illumination.
        self.moon_cache = TimedCache()
        # Its own clock, and a much slower one: the series is daily closes,
        # which do not move between refreshes of the prices beside them.
        self.history_caches = {
            "quotes": TimedCache(),
            "fx": TimedCache(),
            "crypto": TimedCache(),
        }
        self._history_lock = threading.Lock()
        self._history_refreshing = set()
        self._moon_lock = threading.Lock()
        self._moon_refreshing = False
        # Coordinates never change, so the geocode is cached for the life of
        # the process rather than on a TTL (T3.4 step 1). Configured ones are
        # that cache pre-filled, and a broken pair fails startup here.
        self.coords = providers_openmeteo.coords_from_config(config)
        # Validated once, here, rather than per request. A bad name is a
        # startup failure with a console in front of the owner (ADR 0015);
        # `main` catches the ValueError and exits. Constructing an App with a
        # broken `actions` in a test raises for the same reason and that is
        # the behaviour being asserted.
        self.enabled_actions = actions_module.enabled_actions(config.get("actions"))
        # Validated here for the same reason, and raising ValueError the same
        # way: a misspelled provider is found by whoever restarts the server.
        self.calendar_accounts = providers_calendar.accounts_from_config(
            config.get("calendar_accounts"))
        providers_calendar.check_config(config)
        self.wall_clock = wall_clock or (lambda: datetime.datetime.now(datetime.timezone.utc))
        # Validated here like the coordinates: a malformed window is a startup
        # failure, not a gate that silently never opens.
        self.b3_hours = market_hours.hours_from_config(config)
        # When each B3 cache last *succeeded*, by the wall clock. The gate
        # holds a value only if it was fetched after the latest close, and
        # TimedCache's monotonic clock cannot say that.
        self._b3_fetched = {"prices": None, "history": None}
        self.tokens = oauth.TokenStore(tokens_path or SCRIPT_DIR / TOKENS_FILENAME)
        self.credentials = {
            f"{provider}/{name}": oauth.Credentials(
                f"{provider}/{name}", provider, config, self.tokens, post=oauth_post)
            for provider, name in self.calendar_accounts
        }
        self.agenda_cache = TimedCache()
        # The output volume the bar draws (T8.4), read off the request path
        # like the agenda: on Windows a read is a PowerShell compile, seconds
        # long, and /quotes must answer the phone in five.
        self._volume_level = None
        self._volume_at = None
        self._volume_lock = threading.Lock()
        self._volume_refreshing = False
        # Bumped by every set, so a background read that started before a set
        # and finished after it drops its older answer (found by review).
        self._volume_generation = 0
        self._agenda_lock = threading.Lock()
        self._agenda_refreshing = False

    # How old a volume reading may be before the next /quotes asks again. The
    # bar is the last known level, like the mute cross; somebody turning the
    # knob on the PC shows up at the next data cycle after this. Two minutes
    # on Windows, where every read is a PowerShell `Add-Type` compile, and the
    # phone asks around the clock while the session is logged in.
    VOLUME_TTL_S = 20
    VOLUME_TTL_WINDOWS_S = 120

    def volume_level(self):
        """The last measured output volume, 0..100 or None, never blocking."""
        now = self.clock()
        with self._volume_lock:
            ttl = self.VOLUME_TTL_WINDOWS_S if os.name == "nt" else self.VOLUME_TTL_S
            stale = self._volume_at is None or now - self._volume_at >= ttl
            start = stale and not self._volume_refreshing
            if start:
                self._volume_refreshing = True
                generation = self._volume_generation
        if start:
            def run():
                level = actions_module.read_volume()
                with self._volume_lock:
                    self._volume_refreshing = False
                    if generation != self._volume_generation:
                        return
                    self._volume_level = level
                    self._volume_at = self.clock()
            threading.Thread(target=run, name="volume-read", daemon=True).start()
        return self._volume_level

    def set_volume(self, level):
        """Set the output volume; returns the measured level. Raises like run_action."""
        measured = actions_module.set_volume(level)
        with self._volume_lock:
            self._volume_generation += 1
            self._volume_level = measured
            self._volume_at = self.clock()
        return measured

    def run_action(self, action):
        """Execute an enabled action, or raise. Never called with an unknown id.

        The membership test is the caller's (`route`), and it is deliberately
        not repeated here: two places deciding what is enabled is two places
        that can disagree about it.
        """
        return actions_module.run_action(action)

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
        # Read once, like `now`: the prices, the history and the label must
        # not land on different sides of a boundary in one payload.
        wall = self.wall_clock()

        producers = {
            "quotes": self._stamped("prices", lambda: providers_brapi.load(
                config.get("quotes", []),
                token=config.get("brapi_token", ""),
                per_request=config.get("brapi_symbols_per_request", 1),
            )),
            "fx": lambda: providers_awesomeapi.load(config.get("fx", [])),
            "crypto": lambda: providers_binance.load(config.get("crypto", [])),
        }

        history = self._history(now, wall)

        wanted = {"quotes": len(config.get("quotes", [])),
                  "fx": len(config.get("fx", [])),
                  "crypto": len(config.get("crypto", []))}

        payload = {}
        stale = False
        for market, produce in producers.items():
            cache = self.market_caches[market]
            if market == "quotes" and self._held_until_the_open("prices", cache, wall):
                rows, market_stale = cache.value, cache.stale
            else:
                rows, market_stale = cache.get(now, ttl, produce)
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
        # Whether B3's session is running, for the CLOSED label beside the B3
        # title. Decided here and not on the phone, unlike `night`: the window
        # is the exchange's, in Sao Paulo, and follows US daylight saving --
        # a rule the page would have to be rebuilt to learn (market_hours.py).
        payload["b3Open"] = market_hours.exchange_open(wall)
        # Not a market fact, and it rides here anyway: /quotes and /weather are
        # the only two things the phone asks for, DataPoller merges them into
        # the one payload the page gets, and a third endpoint would be a third
        # request per cycle for a string that changes when a human edits a file.
        # /quotes rather than /weather because /quotes is already the payload's
        # carrier -- it is where `stale` is decided for the whole panel.
        payload["theme"] = config.get("theme", "")
        # The night profile's window, and it rides here for the same reason
        # `theme` does: /quotes is the payload's carrier, and a third endpoint
        # would be a third request a cycle for two strings a human edits by
        # hand. Changing when the panel dims must never mean rebuilding the
        # APK (ADR 0013), which is the whole reason these are config at all.
        #
        # Sent as written, never as a boolean. The window is configured here
        # and evaluated against *the phone's* clock -- by js/format.js for the
        # glow and by NightWindow.java for the backlight -- because the panel
        # is the thing whose screen dims and the phone is the thing sitting on
        # the desk. A server that sent `night: true` would be answering with
        # its own timezone, and a panel that had been moved would dim an hour
        # late for ever with nothing to explain why.
        # Rides here with `theme` and `night`, and for the same reason: /quotes
        # is the payload's carrier and a third endpoint would be a third
        # request a cycle for a string a human edits by hand.
        payload["language"] = config.get("language", "")
        payload["night"] = {
            "start": config.get("night_start", ""),
            "end": config.get("night_end", ""),
        }
        # Which buttons the panel draws, riding here for the third time and the
        # same reason as `theme` and `language`: /quotes is the payload's
        # carrier. Adding a third button later must be a line in config.toml
        # and not a rebuild of the APK (ADR 0013), which it cannot be if the
        # page has to be told what exists.
        #
        # The **enabled** ids, already validated against the catalogue at
        # startup -- not the catalogue itself. A panel that drew a button for
        # an action the server would answer 404 to is a button that does
        # nothing, which T8.2 step 7 calls worse than no button at all.
        payload["actions"] = list(self.enabled_actions)
        # The volume bar's level (T8.4), when the bar is enabled; null when it
        # is not, so the key is always there for the payload contract.
        payload["volume"] = ({"level": self.volume_level()}
                             if actions_module.VOLUME in self.enabled_actions else None)
        # The next meetings (T9.1), riding /quotes for the fourth time and for
        # the same reason. Always present, even with no account configured, so
        # DataPayload.merge and mock.js are held to the key by the payload
        # contract rather than by somebody remembering it.
        #
        # The meeting alerts (T9.5) ride inside it, on a copy: the cached
        # value is shared between requests, and the page reads them only
        # where it reads the events.
        payload["agenda"] = dict(self.agenda(),
                                 alerts=providers_calendar.alerts_from_config(config))
        return payload

    def agenda(self):
        """`{accounts, events, failed}`, served from cache and never blocking.

        Refreshed off the request path, like the moon and the histories: one
        Google account is a token refresh, the calendar list and one events
        call per shown calendar (ADR 0019), each with a ten second timeout,
        against a phone that gives the whole request five.
        A cold start therefore serves no events for one cycle.

        The cached value is what the last refresh returned, whole, and
        `providers_calendar.load` never raises, so there is no "last good
        value" to fall back on. A failed account is in `failed`, not in
        `events`. That is the "never stale" rule of ADR 0017, kept by
        construction rather than by a flag.
        """
        if not self.calendar_accounts:
            return {"accounts": 0, "events": [], "failed": []}
        ttl = self.config.get("calendar_interval_s", 300)
        if not self.agenda_cache.fresh_at(self.clock(), ttl):
            self._refresh_agenda_async(ttl)
        return self.agenda_cache.value or {
            "accounts": len(self.calendar_accounts), "events": [], "failed": []}

    def _produce_agenda(self):
        return providers_calendar.load(
            self.calendar_accounts, self.credentials, self.wall_clock(),
            lookahead_h=self.config.get("calendar_lookahead_h", 24),
            show_titles=self.config.get("calendar_show_titles", True) is True)

    def _refresh_agenda_async(self, ttl):
        """One background refresh of the agenda, or leave the running one alone."""
        with self._agenda_lock:
            if self._agenda_refreshing:
                return
            self._agenda_refreshing = True

        def run():
            try:
                self.agenda_cache.get(self.clock(), ttl, self._produce_agenda)
            except Exception:  # noqa: BLE001 - a bug here must not kill the server
                traceback.print_exc()
            finally:
                with self._agenda_lock:
                    self._agenda_refreshing = False

        threading.Thread(target=run, name="agenda", daemon=True).start()

    def warm_agenda(self):
        """Start the first calendar fetch at startup, like `warm_history`."""
        if self.calendar_accounts:
            self._refresh_agenda_async(self.config.get("calendar_interval_s", 300))

    def _history(self, now, wall=None):
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
            if market == "quotes" and self._held_until_the_open(
                    "history", cache, wall or self.wall_clock()):
                pass
            elif not cache.fresh_at(now, self._history_ttl(market)):
                self._refresh_history_async(market)
            history[market] = cache.value or {}
        return history

    def _stamped(self, kind, produce):
        """`produce`, recording the wall-clock instant it last succeeded.

        Stamped at completion, and only on success: a raise skips the line,
        so a failure never makes an old value look like a fresh close.
        """
        def run():
            value = produce()
            self._b3_fetched[kind] = self.wall_clock()
            return value
        return run

    def _held_until_the_open(self, kind, cache, wall):
        """Whether B3's cache holds the last answer brapi will have before the open.

        Only brapi's market, which the callers check: FX trades around the
        clock on weekdays and crypto never stops. Three conditions, and each
        one closes a way of freezing the wrong thing until Monday:

        - the market is shut now;
        - the value is complete -- a cold start, or a ticker a 429 dropped,
          is fetched as before, so a PC that logs in on a Saturday still
          shows Friday's close and no row stays missing all night;
        - it succeeded *after the latest close*. A price from 16:50, left by
          an hour's `quotes_interval_s` or by a PC that slept at noon, is
          intraday and is refreshed once more before anything is held. This
          is also what retries a failure: a timeout at 17:40 leaves the old
          rows with `stale` set and never moves the stamp (`_stamped`), so
          they are older than the close and are asked for again.

        Everything the panel polls in between is served from what is on
        hand, which costs brapi nothing.
        """
        value = cache.value
        if not value:
            return False
        if len(value) < len(self.config.get("quotes", [])):
            return False
        if market_hours.is_open(wall, self.b3_hours):
            return False
        fetched = self._b3_fetched[kind]
        close = market_hours.last_close(wall, self.b3_hours)
        return fetched is not None and close is not None and fetched >= close

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
            return self._stamped("history", lambda: providers_brapi.load_history(
                config.get("quotes", []), token=config.get("brapi_token", ""), days=days
            ))
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
        """`{tempC, minC, maxC, code, isDay, moon, city, stale}` for the city."""
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
        # The moon rides inside the weather object and that is deliberate:
        # DataPayload.merge on the Android side copies this object whole and
        # only strips its `stale`, so a key added here reaches the page with no
        # Java change. A key at the payload's top level is the three-edit trap
        # that cost T6.4 an evening -- `theme`, `night` and `language` each had
        # to be added to `merge` by hand.
        #
        # Cached separately from the forecast, and asked for separately: a
        # forecast outage must not take the moon with it, because the moon is
        # arithmetic over a table and is right even when the weather is
        # unknown. `moon_phase` never raises -- it falls back to the mean
        # synodic model and says `source: "mean"` when it does.
        # **Never on the request path**, which is the other half of what the
        # review found. `weather()` is served synchronously, `upstream`'s
        # timeout is 10s and DataPoller's is 5s, and `DataPayload.merge`
        # returns null if either body fails -- so a slow USNO would have
        # dropped the *whole* payload for that cycle, quotes and fx and crypto
        # and an already-fresh weather with it, to fetch the thing this
        # module's own docstring calls the least important on the panel.
        #
        # Same shape as the sparkline histories: serve what is cached, start a
        # background refresh when it has aged out, and never block. The moon
        # can afford it more than they can -- it moves three points a day.
        moon = self.moon_cache
        ttl = config.get("moon_interval_s", 21600)
        if not moon.fresh_at(self.clock(), ttl):
            self._refresh_moon_async(ttl)
        # And the fallback is here rather than inside the provider, so the
        # cache can record a failure, keep retrying, and say `mean` only for as
        # long as it has nothing better.
        payload["moon"] = moon.value or providers_usno.synodic_phase()
        return payload

    def _refresh_moon_async(self, ttl):
        """One background refresh of the moon, or leave the running one alone.

        TimedCache's lock would make the second caller wait for the first
        rather than letting it through, which is exactly the blocking this
        exists to avoid.
        """
        with self._moon_lock:
            if self._moon_refreshing:
                return
            self._moon_refreshing = True

        def run():
            try:
                self.moon_cache.get(self.clock(), ttl, providers_usno.moon_phase)
            except Exception:
                # TimedCache already keeps the error and the last good value;
                # a thread that dies loudly here would only print a traceback
                # into a journal nobody reads for a moon.
                pass
            finally:
                with self._moon_lock:
                    self._moon_refreshing = False

        threading.Thread(target=run, name="moon", daemon=True).start()


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


# An id is lowercase letters, digits and hyphens, and starts with one of the
# first two. Everything else -- a separator, a semicolon, an ampersand, a
# newline, a space, a percent-escape -- is not an id and never reaches the
# catalogue. This is an allowlist of *characters* in front of an allowlist of
# *names*, which is belt and braces on purpose: ADR 0015's promise is that
# nothing from the request is ever interpolated, and the cheapest way to keep
# a promise like that is to have nothing interesting survive the front door.
#
# Matched with `fullmatch`, not `match`: Python's `$` also matches *before* a
# trailing newline, so `^...$` would accept `mute-audio\n` -- an id with a
# newline in it, which the paragraph above says is not an id.
ACTION_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def action_id(path):
    """Pure: the id in `/action/<id>`, or None if `path` is not that shape.

    One segment, non-empty, no nesting, and nothing outside `[a-z0-9-]`. The
    id is a key in `actions.CATALOGUE` and is never turned into a command, a
    path or an argument; matching narrowly here is the first half of that.
    """
    prefix = "/action/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix):]
    return rest if ACTION_ID_RE.fullmatch(rest) else None


def volume_level_in(path):
    """Pure: the level in `/action/volume/<0-100>`, or None for any other path.

    The only route with a value in it (ADR 0015's third amendment). The text
    becomes an int in `actions.parse_level` here, before anything else runs,
    and that int is all that travels on.
    """
    prefix = "/action/" + actions_module.VOLUME + "/"
    if not path.startswith(prefix):
        return None
    return actions_module.parse_level(path[len(prefix):])


def apk_to_serve(directory):
    """Which `*.apk` in `directory` `/app` hands over, or None.

    **The release build wins whenever there is one**, however old it is. Newest
    by mtime was the first rule here and it was wrong in the one way that
    costs a person a trip to the phone: `out/` holds `app-debug.apk` and
    `desk-panel-release.apk` side by side, `make apk` is assembleDebug, and a
    debug-signed APK cannot install over the release-signed one the panel
    actually runs. The failure is INSTALL_FAILED_UPDATE_INCOMPATIBLE and the
    only way past it is an uninstall, which drops the MIUI toggles.

    Newest-by-mtime is still the rule *among the rest*, for the case that has
    no release build at all: a fresh checkout where somebody has only ever run
    `make apk`.

    A directory that does not exist is the same answer as an empty one -- a
    fresh clone has no `out/`, and that is not an error, it is "build first".
    """
    release = directory / RELEASE_APK_NAME
    if _is_readable_file(release):
        return release

    try:
        children = list(directory.iterdir())
    except OSError:
        return None

    # is_file() and not just the suffix: `out/` already holds a directory
    # (baselineProfiles), and a directory named `x.apk` would be picked, then
    # read -- IsADirectoryError, surfacing as a 500 on a route whose whole job
    # is to hand over a file. stat() is guarded for the same reason one step
    # further out: a dangling symlink answers iterdir() and not stat().
    candidates = []
    for child in children:
        if child.suffix != ".apk":
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        if child.is_file():
            candidates.append((stat.st_mtime, child))
    if not candidates:
        return None
    return max(candidates)[1]


def _is_readable_file(path):
    try:
        return path.is_file()
    except OSError:
        return False


def attachment_filename(name):
    """Pure: `name` if it is safe to put in a header, else a fixed fallback.

    `send_header` does no validation, so a filename carrying a quote or a CRLF
    would break the response or inject a header into it. Selection is by what
    is in `out/`, which is build output on a good day and whatever landed there
    on a bad one, so this is not hypothetical enough to skip.
    """
    return name if SAFE_FILENAME.match(name) else "app.apk"


def apk_download(directory):
    """The `/app` response: the newest APK in `directory`, or a 404 that says
    what to do about it.

    The 404 body is plain text and reads like a sentence because the client
    here is a person holding a phone, not the panel: every other error in this
    file is JSON because the panel is what reads it.
    """
    apk = apk_to_serve(directory)
    body = None
    if apk is not None:
        try:
            body = apk.read_bytes()
        except OSError:
            # The file was there when it was chosen and is not there now, or
            # cannot be read: a build replacing it mid-request, a dangling
            # symlink. "There is not one" is the accurate answer and the
            # useful one; the alternative is a 500 that says nothing.
            body = None
    if body is None:
        return (
            404,
            b"No APK in out/. Build one first:\n"
            b"    docker compose -f docker/compose.yml run --rm build ./gradlew assembleRelease\n",
            "text/plain; charset=utf-8",
            (),
        )
    # The filename is the only reason this header is here. Without it the
    # browser saves the download as "app", with no extension, and Android
    # will not open it.
    disposition = f'attachment; filename="{attachment_filename(apk.name)}"'
    return 200, body, APK_CONTENT_TYPE, (("Content-Disposition", disposition),)


def index_page(directory, offer_apk=True):
    """One page, one link, so the phone only has to remember host and port.

    It exists because typing `/app` on a phone keyboard is worse than tapping
    a link, and because a bare host:port answering 404 reads like the server
    is broken.
    """
    apk = apk_to_serve(directory) if offer_apk else None
    try:
        size = apk.stat().st_size if apk is not None else None
    except OSError:
        size = None
    if not offer_apk:
        # Said rather than hidden: the page is where somebody goes looking
        # for the APK, and a missing link with no reason reads as a bug.
        offer = "<p>The APK is not served here (<code>serve_apk = false</code>).</p>"
    elif apk is None or size is None:
        offer = "<p>No APK built yet.</p>"
    else:
        offer = (
            f'<p><a href="/app">Install {html.escape(apk.name)}</a> '
            f"({size / (1024 * 1024):.1f}&nbsp;MB)</p>"
        )
        if apk.name != RELEASE_APK_NAME:
            # Worth a sentence rather than a silent download: this build will
            # refuse to install over a release-signed one, and the error
            # Android shows for that does not say why.
            offer += (
                "<p>This is not the release build. It will not install over one "
                "&mdash; run <code>assembleRelease</code> first.</p>"
            )
    body = (
        "<!doctype html><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "<title>desk-panel</title>"
        "<style>body{font:16px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;"
        "background:#0b0f14;color:#d7e0ea}a{color:#5ad1e6}</style>"
        "<h1>desk-panel</h1>"
        f"{offer}"
        "<p><a href=\"/ping\">/ping</a> &middot; <a href=\"/quotes\">/quotes</a> "
        "&middot; <a href=\"/weather\">/weather</a></p>"
    )
    return 200, body.encode("utf-8"), "text/html; charset=utf-8", ()


def serves_apk(app):
    """Whether `/app` may hand out the APK. Off without an app (ADR 0018)."""
    return bool((getattr(app, "config", None) or {}).get("serve_apk", False))


def route(method, path, app=None, request_headers=None, channel="plain"):
    """Routing: (method, path) -> (status, body_bytes, content_type, headers).

    The returned `headers` is extra response headers only -- Content-Type and
    Content-Length are the handler's, and every route but `/app` leaves it
    empty.

    `app` supplies the data routes; without one they answer 503 rather than
    pretending, which is what lets the existing two-argument tests keep
    asserting that /ping and 404 need no state at all. `/app` needs no app:
    what it serves is a property of the checkout, not of the panel.

    `request_headers` is the *incoming* headers and exists for exactly one
    route: `POST /action/<id>` is the only one that changes the machine, and
    it is the only one that has to know whether a browser sent the request.
    Every other route reads none of it, which is why it stays optional rather
    than becoming a parameter the whole file threads around. The one header
    every route does read is `Host`, before anything else: see host_allowed.

    `channel` is which listener the request arrived on, "plain" or "tls".
    With panel_key set, data and presses answer only on "tls" and only with
    the key (T9.4, ADR 0018); `/ping` answers on both, always.
    """
    if request_headers is not None:
        extra = (getattr(app, "config", None) or {}).get("allowed_hosts", [])
        if not host_allowed(request_headers.get("Host"), extra):
            return _json(421, {"error": "unknown host"})

    if method == "GET" and path == "/ping":
        # Still one fact first: answering is the login (invariant 2). The
        # display rides along so the phone can also sleep when nobody is
        # looking (ADR 0020); without an app there is nobody to ask, and the
        # body stays what it always was.
        if app is None:
            return _json(200, {"ok": True})
        reader = getattr(app, "display", None) or display_module.Fixed()
        return _json(200, {"ok": True, "display": reader.state()})

    if method == "GET" and path == "/app":
        if not serves_apk(app):
            return 404, b"", "text/plain", ()
        return apk_download(APK_DIR)

    if method == "GET" and path == "/":
        return index_page(APK_DIR, offer_apk=serves_apk(app))

    # Every POST under /action/, matched or not: a new route shape there
    # (the volume's /action/volume/<n>) must never be one that skips the key.
    data_route = (method == "GET" and path in ("/quotes", "/weather", "/spectrum")) or (
        method == "POST" and path.startswith("/action/"))
    if data_route and app is not None and not private.authorized(
            getattr(app, "config", None) or {}, request_headers, channel):
        return _json(401, {"error": "unauthorized"})

    if method == "GET" and path == "/quotes":
        if app is None:
            return _json(503, {"error": "not configured"})
        return _json(200, app.quotes())

    if method == "GET" and path == "/weather":
        if app is None:
            return _json(503, {"error": "not configured"})
        return _json(200, app.weather())

    if method == "GET" and path == "/spectrum":
        # The one route whose body is not bytes: a generator of frame lines,
        # which the handler writes as they come (T8.5, ADR 0021). 404 when
        # the bars are off or cannot be captured here, so the phone stops
        # asking for a while instead of retrying a stream that never comes.
        hub = getattr(app, "spectrum", None)
        if hub is None:
            return 404, b"", "text/plain", ()
        return 200, hub.frames(), "text/plain; charset=us-ascii", (
            ("Cache-Control", "no-store"),)

    if method == "POST":
        level = volume_level_in(path)
        if level is not None:
            return run_volume(level, app, request_headers)
        action = action_id(path)
        if action is not None and action != actions_module.VOLUME:
            return run_action(action, app, request_headers)

    return 404, b"", "text/plain", ()


def host_allowed(host, extra=()):
    """Pure: whether a request's `Host` header names this PC the way a friend would.

    **The attack this closes is DNS rebinding.** A page on `evil.example`
    re-points its own name at this PC's LAN address, and from then on its
    requests to `evil.example:8777` are same-origin, so it can read the
    replies. With the calendar on `/quotes` that would hand a stranger the
    owner's meetings without them being anywhere near the Wi-Fi (ADR 0017).
    Every such request carries the attacker's hostname, because that is the
    name the browser resolved.

    So the header must be an IP literal (v4, or v6 in brackets), `localhost`,
    or a name the owner listed in `allowed_hosts`. The phone, `curl` and
    `probe.py` all address the PC by IP. A request with no Host at all is
    HTTP/1.0, which no browser sends, and is let through.
    """
    if host is None:
        return True
    host = host.strip()
    if host.startswith("["):
        name = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        name = host.split(":", 1)[0]
    else:
        name = host
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    name = name.lower().rstrip(".")
    if name == "localhost":
        return True
    return name in {str(h).strip().lower().rstrip(".") for h in extra or ()}


def sent_by_a_browser(request_headers):
    """True if this POST came from a page rather than from the panel.

    **The drive-by this closes.** A cross-origin
    `<form method=post enctype=text/plain action="http://<pc>:8777/action/mute-audio">`
    is a CORS *simple request*: no preflight, so nothing on this server gets a
    chance to refuse it, and the response being unreadable does not matter
    because the side effect has already happened. Any page the owner visits
    could toggle their microphone. ADR 0015 ruled out `GET` for exactly that
    reason and then described the endpoint as "as trustworthy as the LAN",
    which this widens to "as trustworthy as every site the owner opens".
    Found by review.

    The test is not a token, because a token would have to live in the APK and
    that is the thing `.env` and config.toml exist to prevent (ADR 0013). It is
    that **a browser says so about itself**: the Fetch standard requires
    `Origin` on every non-GET request, and `Sec-Fetch-Site` rides along on the
    engines that have it. The panel's own client is Java's
    `HttpURLConnection`, which sends neither, and so do `curl` and `probe.py`
    -- which is what keeps T8.1's acceptance line meaning what it says.

    A LAN attacker with a socket can of course omit both. That is unchanged
    and is the threat model the ADR already states; this closes the far wider
    hole of not needing to be on the LAN at all.
    """
    if request_headers is None:
        return False
    if request_headers.get("Origin"):
        return True
    site = (request_headers.get("Sec-Fetch-Site") or "").strip().lower()
    return bool(site) and site != "none"


def run_action(action, app, request_headers=None):
    """`POST /action/<id>` -- the only route that changes this machine.

    ADR 0015 is the decision and `server/actions.py` is the catalogue. The
    order of the checks below is the security property, not a style: an id
    that is not enabled returns **404 having run nothing at all**, which is
    why membership is tested before anything is looked up, let alone spawned.

    The browser check sits *after* the allowlist on purpose. An unknown id
    does nothing either way, so refusing it first would buy nothing and would
    change what `probe.py --serve --url /action/not-an-action` means, which
    T8.1's acceptance asserts.

    The status codes say different things and a caller depends on it:
      404  no such action here -- unknown, or known and not enabled
      403  a browser sent it; see sent_by_a_browser
      501  this platform has no implementation of an action that is enabled
      500  it ran and failed, or timed out
      503  the server has no config loaded, like every other data route
    """
    if app is None:
        return _json(503, {"error": "not configured"})
    if action not in getattr(app, "enabled_actions", ()):
        # Deliberately the same answer for "no such id" and "not enabled":
        # the endpoint does not tell an unauthenticated caller which actions
        # exist but are switched off.
        return _json(404, {"error": "unknown action"})
    if sent_by_a_browser(request_headers):
        print(
            f"action {action}: refused, the request carries browser headers "
            f"(Origin={request_headers.get('Origin')!r})",
            file=sys.stderr,
        )
        return _json(403, {"error": "not from a browser"})

    try:
        state = app.run_action(action)
    except actions_module.Unsupported as exc:
        print(f"action {action}: {exc}", file=sys.stderr)
        return _json(501, {"error": "not implemented on this platform"})
    except actions_module.ActionError as exc:
        # The command's own stderr goes to the log, where the owner can read
        # it, and never into the response (ADR 0015).
        print(f"action {action}: {exc}", file=sys.stderr)
        return _json(500, {"error": "action failed"})
    return _json(200, {"ok": True, "id": action, "state": state})


def run_volume(level, app, request_headers=None):
    """`POST /action/volume/<level>` -- run_action's checks, in its order, plus
    the level. `state` in the answer is the level the mixer then reports, as a
    string, or "unknown"."""
    if app is None:
        return _json(503, {"error": "not configured"})
    if actions_module.VOLUME not in getattr(app, "enabled_actions", ()):
        return _json(404, {"error": "unknown action"})
    if sent_by_a_browser(request_headers):
        print("action volume: refused, the request carries browser headers", file=sys.stderr)
        return _json(403, {"error": "not from a browser"})
    try:
        measured = app.set_volume(level)
    except actions_module.Unsupported as exc:
        print(f"action volume: {exc}", file=sys.stderr)
        return _json(501, {"error": "not implemented on this platform"})
    except actions_module.ActionError as exc:
        print(f"action volume: {exc}", file=sys.stderr)
        return _json(500, {"error": "action failed"})
    state = "unknown" if measured is None else str(measured)
    return _json(200, {"ok": True, "id": actions_module.VOLUME, "state": state})


def _json(status, payload):
    """(status, body, content_type, headers) for a JSON response."""
    return status, json.dumps(payload).encode("utf-8"), "application/json", ()


class Handler(BaseHTTPRequestHandler):
    """Dumb by design: routes to `route()` and serialises its result."""

    def __init__(self, *args, app=None, channel="plain", **kwargs):
        # Before super().__init__, which handles the whole request before it
        # returns -- anything set afterwards would not exist yet when
        # do_GET runs.
        self.app = app
        self.channel = channel
        super().__init__(*args, **kwargs)

    def _handle(self, method):
        # HEAD is GET without the body, by definition, so it routes as GET and
        # the body is dropped on the way out. Content-Length still describes
        # the body a GET would have returned, which is what makes a HEAD worth
        # making -- see T3.6's acceptance, which asserts the type without
        # downloading two megabytes.
        routed = "GET" if method == "HEAD" else method
        try:
            status, body, content_type, headers = route(
                routed, self.path, getattr(self, "app", None), self.headers,
                getattr(self, "channel", "plain"),
            )
        except Exception:  # noqa: BLE001 - deliberately everything
            # route() used to be pure; it does I/O now, and TimedCache
            # re-raises anything that is not an UpstreamError on purpose --
            # a bug in a normaliser must not be laundered into "stale".
            # Without this guard socketserver prints the traceback and closes
            # the socket with no status line, so the phone sees an IOException
            # and the operator sees nothing. A 500 is a failure somebody can
            # read; a reset connection is one they have to guess at.
            traceback.print_exc()
            status, body, content_type, headers = _json(500, {"error": "internal error"})
        if not isinstance(body, bytes):
            self._stream(status, body, content_type, headers, method)
            return
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if body and method != "HEAD":
            self.wfile.write(body)

    def _stream(self, status, frames, content_type, headers, method):
        """Writes a streaming body (`/spectrum`) until it ends or the client goes.

        No Content-Length, so the end of the body is the end of the
        connection. Every frame is flushed: a frame that sits in a buffer is
        a bar that moves late. Closing the generator is what tells the hub
        this watcher has left, so it happens however the loop ends.
        """
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Connection", "close")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.close_connection = True
            if method == "HEAD":
                return
            for line in frames:
                self.wfile.write(line)
                self.wfile.flush()
        except OSError:
            # The phone went away, which is how every stream ends but the
            # server's own time limit.
            pass
        finally:
            frames.close()

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

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


class TlsHandler(Handler):
    """Handler for the TLS listener. A timeout, because the handshake runs
    in this thread (see TlsServer) and a client that opens a connection and
    says nothing must cost one thread for a while, not for ever."""

    timeout = private.TLS_TIMEOUT_S


class TlsServer(Server):
    """The private listener: data and presses, over TLS (T9.4, ADR 0018).

    `do_handshake_on_connect=False`, so accept() returns at once and the
    handshake happens on the request thread's first read. With the default,
    one slow or hostile client would stall accept() and with it every other
    client of this port.
    """

    def __init__(self, address, handler, ssl_context):
        super().__init__(address, handler)
        self.socket = ssl_context.wrap_socket(
            self.socket, server_side=True, do_handshake_on_connect=False)

    def handle_error(self, request, client_address):
        # One line, not a traceback: a plain-HTTP client or a scanner on this
        # port fails the handshake, and that is noise, not a bug.
        exc = sys.exc_info()[1]
        print(f"tls: {client_address[0]}: {exc.__class__.__name__}: {exc}", file=sys.stderr)


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

    # Before --check-only returns, not after: `--check-only` is what the
    # launchers and `scripts/after_update.py` run, and a misspelled action is
    # exactly the kind of thing that must be found there rather than by
    # somebody at the desk pressing a button that does nothing (ADR 0015).
    try:
        enabled = actions_module.enabled_actions(config.get("actions"))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    if enabled:
        # Said out loud at every start. This endpoint changes the machine and
        # the server has no authentication; which actions are live is not
        # something to have to go and read a file for. The second half names
        # the command each one resolved to, because a box with neither wpctl
        # nor pactl installed otherwise looks exactly like a working one until
        # somebody presses a button and nothing happens.
        print(f"notice: actions enabled: {', '.join(enabled)}", file=sys.stderr)
        for line in actions_module.describe(enabled):
            print(line, file=sys.stderr)

    # The calendars, checked here for the reason the actions are: before
    # --check-only returns, so the launchers find a typo rather than the owner
    # waiting for a meeting that never shows up.
    try:
        calendar_accounts = providers_calendar.accounts_from_config(
            config.get("calendar_accounts"))
        providers_calendar.check_config(config)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    # The weather's coordinates, for the same reason again: half a pair passing
    # --check-only would only surface as a traceback from App() at the real
    # start, after the launcher had already called the config good.
    try:
        providers_openmeteo.coords_from_config(config)
        market_hours.hours_from_config(config)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    missing = providers_calendar.missing_client_ids(calendar_accounts, config)
    if missing:
        print(f"calendar_accounts needs {', '.join(missing)} in {config_path}; "
              f"see docs/SERVER-SETUP.md", file=sys.stderr)
        sys.exit(1)
    tokens_path = tokens_path_for(config_path)
    if calendar_accounts:
        print(f"notice: calendars: {', '.join(f'{p}/{n}' for p, n in calendar_accounts)} "
              f"(tokens in {tokens_path})", file=sys.stderr)
        if os.name != "nt":
            try:
                tokens_mode = os.stat(tokens_path).st_mode
            except OSError:
                tokens_mode = None
            warning = oauth.tokens_permission_warning(tokens_mode, sys.platform, tokens_path)
            if warning:
                print(warning, file=sys.stderr)

    # The private listener's settings, checked here like everything above:
    # a half configuration, a short key or a certificate that does not load
    # has to be found by --check-only, not by a panel that goes blank.
    for name in ("tls_cert", "tls_key"):
        value = config.get(name) or ""
        if value and not os.path.isabs(value):
            config[name] = str(Path(config_path).resolve().parent / value)
    try:
        private_settings = private.check(config)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    if private_settings is None:
        # Said out loud, like the actions: this is the state in which anyone
        # on the network can read /quotes, calendar titles included.
        print("notice: panel traffic is open: anyone on this network can read /quotes "
              "and press the enabled actions (set panel_key, tls_cert and tls_key; "
              "docs/adr/0018-the-panel-traffic-is-private.md)", file=sys.stderr)
    else:
        print(f"notice: panel traffic is private: data and actions on TLS port "
              f"{private_settings[3]}, /ping on {config.get('port', PORT)}", file=sys.stderr)
    if config.get("serve_apk"):
        print("notice: /app serves the APK to anyone on this network"
              + (", and the APK carries panel_key" if private_settings else ""),
              file=sys.stderr)

    if args.check_only:
        print(f"config OK: {config_path}")
        return

    # The spectrum bars (T8.5), said out loud like the actions: an owner who
    # turned them on and sees flat bars needs to find the reason here.
    spectrum = None
    if config.get("spectrum"):
        factory, reason = spectrum_module.source_for()
        if factory is None:
            print(f"notice: spectrum is on but stays off: {reason}", file=sys.stderr)
        else:
            spectrum = spectrum_module.Spectrum(factory)
            print("notice: spectrum on: /spectrum captures this PC's audio while "
                  "the panel watches", file=sys.stderr)

    port = config.get("port", PORT)
    # functools.partial rather than a class attribute: the app is per-server
    # state, and a class attribute would be shared by every server in a test
    # process that starts more than one.
    app = App(config, tokens_path=tokens_path,
              display=display_module.watcher(config), spectrum=spectrum)
    # Before the socket is bound rather than after: the first poll lands within
    # seconds of a login, and the series should already be on its way.
    app.warm_history()
    app.warm_agenda()
    server = Server((HOST, port), functools.partial(Handler, app=app))
    tls_server = None
    if private_settings is not None:
        _, cert, key_file, tls_port = private_settings
        tls_server = TlsServer((HOST, tls_port),
                               functools.partial(TlsHandler, app=app, channel="tls"),
                               private.context(cert, key_file))
        # A daemon thread: the plain listener in the main thread is the one
        # whose life is the login signal, and this one ends with it.
        threading.Thread(target=tls_server.serve_forever, name="tls-listener",
                         daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if tls_server is not None:
            tls_server.server_close()


if __name__ == "__main__":
    main()
