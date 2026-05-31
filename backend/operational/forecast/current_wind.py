"""Live CURRENT global surface-wind grid (Open-Meteo STANDARD forecast API) for the wind-flow layer.

DISTINCT from the deferred ensemble provider (single-point, 31-member forecast). This hits the standard
`/v1/forecast` endpoint with batched multi-point `current=wind_speed_10m,wind_direction_10m`, then converts
meteorological speed+direction → vector components (u east, v north). It is a COARSE, RELATIVE display field
(a few-degree lattice, interpolated for the globe) — NOT a forecast product; the response labels it so.

Open-Meteo direction is the direction the wind blows FROM (deg clockwise from N), so the wind VECTOR
(toward) is: u = -speed·sin(θ), v = -speed·cos(θ). Getting that sign wrong silently mirrors the field.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

# Open-Meteo free tier: bulk requests are weighted by location COUNT, and the GET URL 414s above
# ~700 coords. So we chunk ≤400 and fetch SERIALLY with 429 backoff (concurrent bursts get rate-limited).
# The grid is coarse + cached for hours upstream, so a slow cold fetch is fine.
_CHUNK = 400
_MAX_RETRIES = 5

WIND_SOURCE = "Open-Meteo current wind @ 10 m (GFS-seamless, ~25 km native)"


class GridWind(BaseModel):
    bbox: tuple[float, float, float, float]  # lat_min, lon_min, lat_max, lon_max
    resolution: float
    nx: int  # columns (longitude), west→east
    ny: int  # rows (latitude), row 0 = NORTH (lat_max), north→south
    u: list[float]  # eastward m/s, row-major (ny×nx)
    v: list[float]  # northward m/s, row-major
    speed: list[float]  # m/s magnitude, row-major
    as_of: str  # ISO-8601 UTC
    source: str
    note: str  # honesty: coarse / interpolated / not a forecast


def wind_uv(speed_ms: float, direction_deg: float) -> tuple[float, float]:
    """Meteorological 'from' direction (deg clockwise from N) + speed → wind VECTOR (toward).
    u = eastward, v = northward (m/s). Wind FROM the north (0°) blows toward the south → v<0, u≈0."""
    rad = math.radians(direction_deg)
    return (-speed_ms * math.sin(rad), -speed_ms * math.cos(rad))


def _lattice(resolution: float) -> tuple[list[float], list[float]]:
    """Cell-center lats (north→south) and lons (west→east) for a global lattice at `resolution`°."""
    nlat = max(1, int(round(180.0 / resolution)))
    nlon = max(1, int(round(360.0 / resolution)))
    lats = [90.0 - resolution * (i + 0.5) for i in range(nlat)]
    lons = [-180.0 + resolution * (j + 0.5) for j in range(nlon)]
    return lats, lons


async def _fetch_chunk(client: httpx.AsyncClient, url: str, chunk: list[tuple[float, float]]) -> list:
    """One batched current= request with exponential 429 backoff. Returns the per-coord results list."""
    params = {
        "latitude": ",".join(f"{c[0]:.3f}" for c in chunk),
        "longitude": ",".join(f"{c[1]:.3f}" for c in chunk),
        "current": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    }
    delay = 1.5
    for _ in range(_MAX_RETRIES):
        resp = await client.get(url, params=params)
        if resp.status_code == 429:
            await asyncio.sleep(delay)
            delay = min(20.0, delay * 1.8)
            continue
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"Open-Meteo error: {data.get('reason')}")
        # A bulk request returns a LIST (one object per coord, in request order); a single coord
        # returns one object. Results align by index with `chunk`.
        return data if isinstance(data, list) else [data]
    raise RuntimeError("Open-Meteo current wind rate-limited (429) after retries.")


async def build_current_wind(forecast_url: str, resolution: float = 6.0) -> GridWind:
    """Fetch the coarse global current-wind grid SERIALLY (rate-limit-friendly). Raises → 502."""
    lats, lons = _lattice(resolution)
    ny, nx = len(lats), len(lons)
    coords = [(lat, lon) for lat in lats for lon in lons]  # row-major north→south, west→east
    n = len(coords)
    u = [0.0] * n
    v = [0.0] * n
    speed = [0.0] * n

    async with httpx.AsyncClient(timeout=30.0) as client:
        for start in range(0, n, _CHUNK):
            results = await _fetch_chunk(client, forecast_url, coords[start : start + _CHUNK])
            for k, item in enumerate(results):
                idx = start + k
                if idx >= n:
                    break
                cur = item.get("current") or {}
                s = cur.get("wind_speed_10m")
                d = cur.get("wind_direction_10m")
                if s is None or d is None:
                    continue  # leave 0 (e.g. a transient null); never fabricate
                spd = float(s)
                u[idx], v[idx] = wind_uv(spd, float(d))
                speed[idx] = spd

    return GridWind(
        bbox=(-90.0, -180.0, 90.0, 180.0),
        resolution=resolution,
        nx=nx,
        ny=ny,
        u=u,
        v=v,
        speed=speed,
        as_of=datetime.now(timezone.utc).isoformat(),
        source=WIND_SOURCE,
        note=(
            f"COARSE live current wind — global {resolution}° lattice (~{int(resolution * 111)} km cells), "
            "interpolated for display. Observed conditions, not a forecast."
        ),
    )
