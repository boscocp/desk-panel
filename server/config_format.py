#!/usr/bin/env python3
"""What a config file *means*, with no file involved.

Every function here is a function of its arguments. `load_config` in
server.py owns the one read; this module owns the bytes-to-dict step, so
TT.2 can cover both formats, both failure shapes and the merge without
writing a temp file -- see server/CLAUDE.md ("keep the request handler
dumb": the same argument, one layer further in).

Two formats, and the second is here only so that nobody's running panel
breaks because a file was renamed (T3.12 step 3):

    config.toml   what the owner should write. Comments, no trailing-comma
                  trap, bare keys, obvious lists -- the whole point of the
                  change, since the file can now carry the catalogue of
                  values that actually work.
    config.json   what the owner may already have. Still read, still
                  valid, and the server says once where the replacement is.

**TOML rather than the YAML that was asked for.** server/CLAUDE.md makes
standard-library-only a hard constraint -- the server has to run on a clean
box -- and PyYAML is a dependency. `tomllib` has been in the standard
library since 3.11, which is exactly this project's floor (T3.11), and
gives every property the request was actually about. Hand-rolling a YAML
subset would have been the worse trade: a format everybody thinks they
know, implemented almost correctly. If YAML is wanted anyway that is a
deliberate break of the stdlib-only rule and belongs in an ADR.
"""
import json
import tomllib
from pathlib import Path

TOML = "toml"
JSON = "json"


class ConfigError(Exception):
    """A missing or malformed config file.

    The message is always safe to print or log: it never contains the
    token or any other config value, only the path involved -- see
    server/CLAUDE.md ("secrets stay here").

    That is a property of the two parsers as much as of this code, and it
    was checked rather than assumed. `tomllib` reports `Invalid value (at
    line 1, column 15)` for `brapi_token = super-secret-token`, and
    `json` reports a position too; neither echoes the text it choked on.
    TT.2 pins it for both formats, because a parser that started quoting
    the offending line would leak the token into a log on the first typo.
    """


def format_for_path(path):
    """Pure: which parser `path` wants, from its suffix alone.

    `.toml` is TOML and everything else is JSON, including a path with no
    suffix at all. Defaulting rather than raising is deliberate:
    `DESK_PANEL_CONFIG=/etc/desk-panel/config` is a reasonable thing for a
    packager to write, and it worked before this task existed.
    """
    return TOML if Path(path).suffix.lower() == ".toml" else JSON


def parse(text, fmt=TOML, name="config"):
    """Pure: config text -> dict, raising ConfigError for anything else.

    One exception type out, whichever parser went in, so callers have one
    thing to catch. `name` only ever appears in the message; nothing here
    touches a filesystem.

    TOML's top level is always a table, so the "not a mapping" branch can
    only fire for JSON in practice. It is written for both anyway -- the
    cost is one line, and a guard that exists only for the format it was
    first needed in is how the next format arrives unguarded.
    """
    if fmt == TOML:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{name} is not valid TOML: {exc}") from None
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{name} is not valid JSON: {exc}") from None

    if not isinstance(data, dict):
        shape = "a table of key = value pairs" if fmt == TOML else "a JSON object"
        raise ConfigError(f"{name} must contain {shape}")
    return data


def merge(data, defaults):
    """Pure: `defaults` overlaid with `data`, one level deep.

    One level on purpose. `actions` is the only nested value and it is a
    whole allowlist: a config that sets it means to replace the default,
    not to extend an inherited one. server/CLAUDE.md calls that allowlist
    closed, and a deep merge would quietly reopen it.
    """
    merged = dict(defaults)
    merged.update(data)
    return merged
