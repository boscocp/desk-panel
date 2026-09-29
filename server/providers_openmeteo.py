#!/usr/bin/env python3
"""Weather, from Open-Meteo.

No API key, for non-commercial use, at 10k requests a day. It goes through
this proxy anyway, so the panel has one code path rather than two
(ADR 0004) — there is no secret here to protect.

Shapes below are measured, 2026-09-19, not read off the docs.

    GET geocoding-api.open-meteo.com/v1/search?name=Sao+Paulo&count=1
    {"results": [{"name": "São Paulo", "latitude": -23.5475,
                  "longitude": -46.63611, "timezone": "America/Sao_Paulo", ...}]}

    GET api.open-meteo.com/v1/forecast?latitude=..&longitude=..
        &current=temperature_2m,weather_code
        &daily=temperature_2m_max,temperature_2m_min&timezone=..
    {"current": {"time": "2026-09-19T11:15", "temperature_2m": 24.0,
                 "weather_code": 2},
     "daily": {"time": ["2026-09-19", "2026-09-20", ...],
               "temperature_2m_max": [26.1, ...],
               "temperature_2m_min": [15.5, ...]}}

**`daily` is a week, not a day.** Today is an index into seven parallel
arrays, and the task file's warning is about which index that is: without the
`timezone` parameter the days are cut on UTC boundaries, so after 21:00 in
São Paulo index 0 is already tomorrow and the panel shows tomorrow's high as
today's. That is a wrong number rather than an error, which is the worst kind.

Two defences, because the parameter alone is a promise rather than a check.
The timezone is passed from `config.timezone`, never a literal — hardcoding
it produced exactly this bug for any city outside America/Sao_Paulo. And
`normalise` does not take index 0: it finds the day whose date matches
`current.time`, so a mismatch costs the min/max rather than silently shifting
them.

**WMO codes stay codes.** Mapping `2` to "partly cloudy" is wording, and
wording belongs to `web/js/format.js`. The server returns data.
"""
import math

from server.upstream import UpstreamError, get_json

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_geocode(city, get=get_json):
    """Resolve `city` to coordinates. The seam TT.2 patches.

    Called once and cached by the caller — the coordinates of a city do not
    move, and geocoding on every poll would spend the daily budget on a
    constant.
    """
    from urllib.parse import quote

    # safe="" so nothing in a city name is left to chance -- quote() leaves
    # "/" alone by default, which is legal in a query value and still a
    # needless thing to rely on.
    return get(
        f"{GEOCODE_URL}?name={quote(str(city), safe='')}&count=1&language=en&format=json"
    )


def normalise_geocode(raw):
    """Pure: the geocoding response -> `{lat, lon, city}`, or None.

    None rather than an exception for "no such place": a city that does not
    resolve is a config mistake the owner has to fix, and the caller turns it
    into a log line naming the city. Raising here would only move that
    decision somewhere with less context.
    """
    # isinstance rather than `raw or {}` -- see providers_brapi.normalise for
    # why a JSON array body is the realistic case this guards.
    if not isinstance(raw, dict):
        return None
    results = raw.get("results")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    lat = _number(first.get("latitude"))
    lon = _number(first.get("longitude"))
    if lat is None or lon is None:
        return None
    return {
        "lat": lat,
        "lon": lon,
        # The resolved name, not the configured one. "Sao Paulo" in config
        # comes back "São Paulo", and showing what was actually found is how
        # a human notices they geocoded the wrong Springfield.
        "city": str(first.get("name") or "").strip() or str(raw.get("_requested", "")),
    }


def coords_from_config(config):
    """Pure: the configured `latitude`/`longitude` -> `{lat, lon, city}`, or None.

    None when neither is set, which leaves the city to be geocoded. A city as
    big as Sao Paulo geocodes to its centre, and a storm over one district is
    not one over another; the pair is how the owner points the forecast at
    their own street. Raises ValueError for half a pair, a non-number or a
    value off the globe: each would otherwise geocode quietly, or ask the
    upstream for a place that does not exist, and the owner would read a
    forecast for somewhere else. `main` runs this before `--check-only`
    returns, so the launchers find a broken pair rather than a traceback.
    """
    lat_raw, lon_raw = config.get("latitude"), config.get("longitude")
    if lat_raw is None and lon_raw is None:
        return None
    if lat_raw is None or lon_raw is None:
        raise ValueError("latitude and longitude must be set together, or neither")
    # Native numbers only. TOML and JSON both carry a float as a float, so a
    # string here is a quoting mistake, and float() would read "1_0" as 10.
    for raw in (lat_raw, lon_raw):
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise ValueError(
                f"latitude and longitude must be numbers, got {lat_raw!r}, {lon_raw!r}")
    lat, lon = float(lat_raw), float(lon_raw)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"latitude {lat} / longitude {lon} is not a place on Earth")
    # The label stays the configured city, spelled as configured ("Sao Paulo",
    # not the geocoder's "São Paulo"): these coordinates name no place, and
    # the geocoder is not asked for one.
    return {"lat": lat, "lon": lon, "city": str(config.get("city") or "")}


def fetch_forecast(lat, lon, timezone, get=get_json):
    """Ask for the current conditions and today's range. The seam TT.2 patches."""
    from urllib.parse import quote

    return get(
        f"{FORECAST_URL}?latitude={lat}&longitude={lon}"
        # is_day is the sun's own answer for these coordinates (T6.13), and it
        # is why the panel can stop drawing a sun after dark. Measured, not read
        # off the docs: at 21:15 on 2026-09-21 in Sao Paulo this endpoint
        # answered {"weather_code": 1, "is_day": 0} -- clear sky, no sun -- and
        # the panel drew a sun because it had never been told the second half.
        "&current=temperature_2m,weather_code,is_day"
        # precipitation_probability_max is the day's chance of rain and is a
        # *daily* field: open-meteo's `current` block has no probability at
        # all, which was checked against the live endpoint rather than the
        # docs. `hourly` has one too, and this deliberately does not use it --
        # see normalise.
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone={quote(str(timezone), safe='')}"
    )


def _is_day(raw):
    """1/0 (or true/false) -> bool, with *anything unanswered* meaning daylight.

    Not a general truthiness cast: None is the upstream declining to say, and
    the safe direction is the one that leaves the panel behaving as it did
    before T6.13 rather than turning it nocturnal on a missing field.
    """
    if raw is None:
        return True
    return bool(raw)


def normalise(raw, city=""):
    """Pure: the response -> `{tempC, minC, maxC, code, isDay, precipProb, city}`.

    Missing pieces come back as None rather than 0. A temperature of zero is
    a real reading in most of the world, so a zero standing in for "no data"
    is a lie the panel cannot detect; `format.js` renders None as a dash.

    `isDay` is the exception and is a real bool, never None: the upstream
    sends 1/0 and the page asks `if (isDay)`, where 0 and None are the same
    answer anyway. Absent means **True**, which is the safe direction of the
    two -- a panel drawing a sun at midnight is the complaint T6.13 came from,
    and one drawing a moon at noon would be stranger still. It also means an
    older server, or a cached body from before this key existed, keeps
    behaving exactly as it did.
    """
    if not isinstance(raw, dict):
        raw = {}
    current = raw.get("current") if isinstance(raw.get("current"), dict) else {}
    daily = raw.get("daily") if isinstance(raw.get("daily"), dict) else {}

    index = _today_index(current.get("time"), daily.get("time"))

    return {
        "tempC": _number(current.get("temperature_2m")),
        "minC": _at(daily.get("temperature_2m_min"), index),
        "maxC": _at(daily.get("temperature_2m_max"), index),
        "code": _int(current.get("weather_code")),
        # The chance of rain **today**, not in the current hour, and the two are
        # not close: measured against the live endpoint at 2026-09-22T00:00 in
        # Sao Paulo, the day's max was 98% while the hour ahead was 31%.
        #
        # The day, because this card is already day-scoped -- the min and max
        # beside it are today's -- and a panel read at a glance must not change
        # the scale of its numbers from one line to the next. The hourly series
        # is the better answer to "should I leave now", which is a question a
        # panel with no interaction cannot be asked.
        #
        # Indexed by the same matched date as the temperatures, never by [0]:
        # without the timezone parameter the daily arrays are cut on UTC days,
        # and after 21:00 in Sao Paulo index 0 is already tomorrow.
        "precipProb": _int(_at(daily.get("precipitation_probability_max"), index)),
        # Missing means daylight, and so does an explicit null. The first cut
        # was `bool(current.get("is_day", 1))`, whose default covers only the
        # absent key: a body carrying `"is_day": null` -- what open-meteo
        # sends for a current field it cannot compute -- went through
        # `bool(None)` and came out False, so the one value that means *no
        # answer* became the decisive answer for night. A moon at noon, from
        # the branch the docstring calls stranger still. Every other field
        # here routes None through `_number`/`_int` and treats it as missing;
        # this one has to do the same before it commits.
        "isDay": _is_day(current.get("is_day")),
        "city": city,
    }


def _today_index(current_time, days):
    """Pure: the index in `days` matching `current_time`'s date, or None.

    Both are already in the requested timezone, so this is a string compare
    on `YYYY-MM-DD` and needs no date parsing and no clock of its own. None
    when they disagree, which is the signal that the timezone parameter did
    not do what it was supposed to.
    """
    if not isinstance(days, list) or not isinstance(current_time, str):
        return None
    today = current_time[:10]
    for i, day in enumerate(days):
        if isinstance(day, str) and day[:10] == today:
            return i
    return None


def _at(values, index):
    """Pure: `values[index]` as a float, or None if either is unusable."""
    if index is None or not isinstance(values, list) or index >= len(values):
        return None
    return _number(values[index])


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    number = _number(value)
    return None if number is None else int(number)


def load(city, timezone, coords=None, get=get_json):
    """Geocode (unless `coords` is supplied) then fetch, and normalise.

    `coords` is the caller's cache. Passing it in rather than caching here
    keeps this module free of state and of a clock, which is what lets TT.2
    test it without either.
    """
    if coords is None:
        located = normalise_geocode(fetch_geocode(city, get=get))
        if located is None:
            raise UpstreamError(f"no coordinates found for city {city!r}")
        coords = located
    raw = fetch_forecast(coords["lat"], coords["lon"], timezone, get=get)
    return normalise(raw, city=coords.get("city") or city), coords


__all__ = ["FORECAST_URL", "GEOCODE_URL", "UpstreamError", "coords_from_config",
           "fetch_forecast", "fetch_geocode", "load", "normalise", "normalise_geocode"]
