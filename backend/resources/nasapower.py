"""NASAPowerProvider — free NASA POWER regional climatology (real fetch).

Verified live 2026-05-30. Facts baked in:
- Regional climatology endpoint, no API key, GeoJSON FeatureCollection response.
- ONE parameter per request, so we fan out one async GET per variable and INNER-JOIN
  cells on (lat, lon). Each feature carries properties.parameter.<PARAM>.ANN (annual mean).
- POWER fills missing cells with -999.0 (mostly ocean/no-data) — the provider DROPS any
  cell where a requested variable is -999/NaN so the cleaning contract holds (no NaN
  reaches the scoring layer). Upstream/parse failures -> RuntimeError (-> 502).
- A single regional request is bounded to a 2°–10° span per axis.
"""

from __future__ import annotations

import asyncio
import math

import httpx

from .base import ResourceProvider
from .constants import (
    MAX_REGION_SPAN_DEG,
    MAX_SPAN_DEG,
    MIN_SPAN_DEG,
    NASA_POWER_BASE_URL,
    NATIVE_RESOLUTION_DEG,
    POWER_COMMUNITY,
    POWER_FILL,
)
from .types import ResourceCell, ResourceGrid

Coord = tuple[float, float]


class NASAPowerProvider(ResourceProvider):
    def __init__(self, base_url: str = NASA_POWER_BASE_URL) -> None:
        self.base_url = base_url

    async def get_resource_grid(
        self,
        bbox: tuple[float, float, float, float],
        resolution: float,
        variables: list[str],
    ) -> ResourceGrid:
        lat_min, lon_min, lat_max, lon_max = bbox
        for span, axis in ((lat_max - lat_min, "lat"), (lon_max - lon_min, "lon")):
            if span < MIN_SPAN_DEG:
                raise ValueError(f"{axis} span {span:.3f}° below NASA POWER minimum {MIN_SPAN_DEG}°.")
            if span > MAX_REGION_SPAN_DEG:
                raise ValueError(f"{axis} span {span:.3f}° exceeds the max region {MAX_REGION_SPAN_DEG}°.")
        if not variables:
            raise ValueError("get_resource_grid requires at least one variable.")

        # A single POWER regional call is capped at 10°/axis; tile larger regions and merge.
        tiles = _tile_bbox(bbox, MAX_SPAN_DEG)
        sem = asyncio.Semaphore(4)

        async with httpx.AsyncClient(timeout=60.0) as client:

            async def fetch(tile: tuple[float, float, float, float]) -> list[ResourceCell]:
                async with sem:
                    return await self._fetch_tile(client, tile, variables)

            tile_cells = await asyncio.gather(*(fetch(t) for t in tiles))

        merged: dict[Coord, ResourceCell] = {}
        for cells in tile_cells:
            for cell in cells:
                merged[(cell.lat, cell.lon)] = cell  # dedup overlapping tile edges
        cells = _coarsen([merged[k] for k in sorted(merged)], resolution)
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=cells)

    async def _fetch_tile(
        self,
        client: httpx.AsyncClient,
        tile: tuple[float, float, float, float],
        variables: list[str],
    ) -> list[ResourceCell]:
        per_var = await asyncio.gather(
            *(self._fetch_param(client, tile, var) for var in variables)
        )
        try:
            return _join_nearest(per_var, variables)
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(f"NASA POWER response malformed: {exc}") from exc

    async def _fetch_param(
        self,
        client: httpx.AsyncClient,
        bbox: tuple[float, float, float, float],
        param: str,
    ) -> dict[Coord, float]:
        lat_min, lon_min, lat_max, lon_max = bbox
        params = {
            "parameters": param,
            "community": POWER_COMMUNITY,
            "latitude-min": lat_min,
            "latitude-max": lat_max,
            "longitude-min": lon_min,
            "longitude-max": lon_max,
            "format": "JSON",
        }
        resp = await client.get(self.base_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        # NB: POWER returns an informational `messages` array even on SUCCESS (e.g. the
        # "pre-computed climatological period 2001-2020" note) — it is NOT an error
        # signal. Rely on `features`; a genuine error yields no features (-> RuntimeError).
        try:
            out: dict[Coord, float] = {}
            for feature in data["features"]:
                lon, lat = feature["geometry"]["coordinates"][:2]
                ann = feature["properties"]["parameter"][param]["ANN"]
                out[(round(float(lat), 4), round(float(lon), 4))] = float(ann)
            return out
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError(f"NASA POWER response malformed for {param}: {exc}") from exc


# Different POWER parameters live on different native grids (radiation ~1°,
# MERRA-2 meteorology ~0.5°×0.625°), so an exact-coordinate join collapses to the few
# shared points. We join by NEAREST NEIGHBOUR onto the finest grid instead.
_JOIN_TOLERANCE_DEG = 1.0


def _nearest(table: dict[Coord, float], lat: float, lon: float) -> tuple[float | None, float]:
    best_v: float | None = None
    best_d2: float | None = None
    for (la, lo), v in table.items():
        d2 = (la - lat) ** 2 + (lo - lon) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2, best_v = d2, v
    return best_v, (best_d2**0.5 if best_d2 is not None else float("inf"))


def _join_nearest(
    per_var: list[dict[Coord, float]], variables: list[str]
) -> list[ResourceCell]:
    """Join all variables onto the FINEST parameter's grid by nearest neighbour. Drops
    any target cell where a variable has no neighbour within tolerance or is -999/NaN."""
    if not per_var or any(not table for table in per_var):
        return []
    target_i = max(range(len(per_var)), key=lambda i: len(per_var[i]))

    cells: list[ResourceCell] = []
    for lat, lon in sorted(per_var[target_i]):
        vals: dict[str, float] = {}
        ok = True
        for i, var in enumerate(variables):
            if i == target_i:
                value, dist = per_var[i][(lat, lon)], 0.0
            else:
                value, dist = _nearest(per_var[i], lat, lon)
            if value is None or dist > _JOIN_TOLERANCE_DEG or value == POWER_FILL or math.isnan(value):
                ok = False
                break
            vals[var] = value
        if ok:
            cells.append(ResourceCell(lat=lat, lon=lon, values=vals))
    return cells


def _tile_bbox(
    bbox: tuple[float, float, float, float], max_span: float
) -> list[tuple[float, float, float, float]]:
    """Split a bbox into a grid of tiles, each at most `max_span` per axis (and, given the
    region cap, never below the API minimum). Tiles cover the bbox exactly."""
    lat_min, lon_min, lat_max, lon_max = bbox

    def bands(lo: float, hi: float) -> list[tuple[float, float]]:
        span = hi - lo
        n = max(1, math.ceil(span / max_span - 1e-9))  # epsilon: span==max_span -> 1 tile
        step = span / n
        return [(lo + i * step, lo + (i + 1) * step) for i in range(n)]

    return [
        (la0, lo0, la1, lo1)
        for (la0, la1) in bands(lat_min, lat_max)
        for (lo0, lo1) in bands(lon_min, lon_max)
    ]


def _coarsen(cells: list[ResourceCell], resolution: float) -> list[ResourceCell]:
    """Optionally subsample the native ~0.5° grid to a coarser target resolution by
    striding unique lat/lon bands. resolution <= native returns the grid unchanged."""
    if resolution <= NATIVE_RESOLUTION_DEG or not cells:
        return cells
    step = max(1, round(resolution / NATIVE_RESOLUTION_DEG))
    lats = sorted({c.lat for c in cells})
    lons = sorted({c.lon for c in cells})
    keep_lats = set(lats[::step])
    keep_lons = set(lons[::step])
    return [c for c in cells if c.lat in keep_lats and c.lon in keep_lons]
