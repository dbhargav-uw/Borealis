"""NOAA NHC active tropical cyclones — CurrentStorms.json (positions + scalars; no key, no headers).

We map the per-storm SCALARS only (id, name, classification, intensity→category, position, movement,
advisory time). Track/cone GIS (zipped shapefiles / KMZ, self-linked per storm) is a deferred fast-follow.
Empty `activeStorms` is the NORMAL case (off-season) — returns []. Coverage: Atlantic + E/Central Pacific.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from storms.types import ActiveStorm, StormsResponse

NHC_SOURCE = "NOAA NHC active storms (CurrentStorms.json)"
NHC_COVERAGE = "NOAA NHC — Atlantic + E/Central Pacific basins only (no W Pacific / N Indian Ocean)."

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def saffir_simpson_category(wind_kt: float) -> int:
    """Saffir–Simpson category from 1-min sustained wind (knots). 0 = tropical storm or weaker."""
    if wind_kt >= 137:
        return 5
    if wind_kt >= 113:
        return 4
    if wind_kt >= 96:
        return 3
    if wind_kt >= 83:
        return 2
    if wind_kt >= 64:
        return 1
    return 0


def _compass(deg: float) -> str:
    return _COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def _to_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _to_float_opt(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _movement(storm: dict) -> str | None:
    direction = _to_float_opt(storm.get("movementDir"))
    speed = _to_float_opt(storm.get("movementSpeed"))
    if direction is None or speed is None:
        return None
    return f"{_compass(direction)} at {int(round(speed))} mph"


def parse_storm(storm: dict) -> ActiveStorm:
    """Map one CurrentStorms.json `activeStorms[]` entry → ActiveStorm. Raises on missing position."""
    storm_id = str(storm["id"])
    wind_kt = _to_float(storm.get("intensity"))
    return ActiveStorm(
        id=storm_id,
        name=(str(storm.get("name", "")).strip() or "Unnamed"),
        basin=storm_id[:2].upper(),
        classification=str(storm.get("classification", "")).strip(),
        category=saffir_simpson_category(wind_kt),
        lat=float(storm["latitudeNumeric"]),
        lon=float(storm["longitudeNumeric"]),
        max_wind_kt=wind_kt,
        min_pressure_mb=_to_float_opt(storm.get("pressure")),
        movement=_movement(storm),
        advisory_time=str(storm.get("lastUpdate", "")),
        source=NHC_SOURCE,
    )


# Named tropical/subtropical cyclones at TROPICAL-STORM strength or stronger. We render only these —
# excluding tropical depressions (TD/SD), potential TCs (PTC), and disturbances/lows/waves/extratropical
# (DB/LO/WV/EX) — so the map shows the handful of real named systems, not every blip.
_NAMED_CYCLONE_CLASS = {"TS", "HU", "STS", "SS"}  # tropical storm / hurricane / subtropical storm
_NON_CYCLONE_CLASS = {"PTC", "TD", "SD", "DB", "LO", "WV", "EX"}
_TS_WIND_KT = 34.0  # tropical-storm threshold


def is_named_cyclone(storm: ActiveStorm) -> bool:
    """True for a genuine NAMED cyclone at TS strength or stronger (the only systems we render)."""
    name = storm.name.strip().lower()
    if not name or name in {"unnamed", "invest"} or name.startswith("invest") or name.isdigit():
        return False
    cls = storm.classification.strip().upper()
    if cls in _NON_CYCLONE_CLASS:
        return False
    return cls in _NAMED_CYCLONE_CLASS or storm.max_wind_kt >= _TS_WIND_KT


def parse_active_storms(payload: dict) -> list[ActiveStorm]:
    """Map the whole CurrentStorms.json payload, keeping only genuine named cyclones (TS+). Skips
    (does not fail on) a malformed storm."""
    storms: list[ActiveStorm] = []
    for raw in payload.get("activeStorms") or []:
        try:
            storm = parse_storm(raw)
        except (KeyError, ValueError, TypeError):
            continue  # one bad storm never breaks the whole feed
        if is_named_cyclone(storm):
            storms.append(storm)
    return storms


async def build_storms_response(url: str) -> StormsResponse:
    """Fetch + normalize. Raises httpx.HTTPError / RuntimeError (→ 502 at the route)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"NHC CurrentStorms.json malformed: {exc}") from exc
    return StormsResponse(
        storms=parse_active_storms(payload),
        as_of=datetime.now(timezone.utc).isoformat(),
        source=NHC_SOURCE,
        coverage=NHC_COVERAGE,
    )
