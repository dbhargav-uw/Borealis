"""OpenMeteoResourceProvider — FINE-resolution climatology from Open-Meteo's ERA5-Land
archive (~0.1°/~11 km, global, no API key). The high-resolution sibling of NASAPowerProvider.

Verified live against the archive API on 2026-05-30. Facts baked in:
- Archive endpoint, `models=era5_seamless` (ERA5-Land ~0.1° for temp + 10 m wind, ERA5 ~0.25°
  for precip + shortwave — ERA5-Land alone returns null for precip/radiation). Multiple points
  per request via comma-separated latitude/longitude (response is an array of per-location
  objects, request order preserved).
- We compute a multi-year CLIMATOLOGY by averaging a fixed window (daily aggregates for
  GHI/temp/precip; hourly wind). Any point with a null/missing value for a requested variable
  is DROPPED so the cleaning contract holds (no NaN reaches scoring); ocean removal for
  `land_only` is finalized by the route's land mask.
- Emits ResourceCell.values keyed by the SAME semantic constants and units as NASA POWER
  (GHI kWh/m²/day, WS50M m/s, T2M °C, PRECTOTCORR mm/day), so every SuitabilityModel is
  unchanged. Parse/transport failures -> RuntimeError (-> 502), matching the POWER provider.

HONEST CONSTRAINT: ERA5-Land has no native 50 m wind. WIND_50M is extrapolated from the 10 m
mean via the power law v50 = v10·(50/10)^α (α≈0.143) — a defensible approximation for a
ranking comparator, not a bankable hub-height figure.
"""

from __future__ import annotations

import asyncio
import math

import httpx

from .base import ResourceProvider
from .constants import (
    GHI,
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_COORDS_PER_REQUEST,
    OPEN_METEO_MAX_CELLS,
    OPEN_METEO_MODEL,
    OPEN_METEO_NATIVE_RES_DEG,
    OPEN_METEO_WINDOW_END,
    OPEN_METEO_WINDOW_START,
    PRECIP,
    TEMP_2M,
    WIND_10M,
    WIND_50M,
    WIND_SHEAR_ALPHA,
)
from .types import ResourceCell, ResourceGrid

Coord = tuple[float, float]

# Semantic variable -> Open-Meteo DAILY aggregate name (one daily call covers all three).
_DAILY_VAR: dict[str, str] = {
    GHI: "shortwave_radiation_sum",      # MJ/m²/day
    TEMP_2M: "temperature_2m_mean",      # °C
    PRECIP: "precipitation_sum",         # mm/day
}
# Semantic variable -> Open-Meteo HOURLY name (both winds derive from the 10 m hourly series).
_HOURLY_VAR: dict[str, str] = {
    WIND_50M: "wind_speed_10m",          # m/s (wind_speed_unit=ms)
    WIND_10M: "wind_speed_10m",          # m/s
}


def _convert(variable: str, daily: dict[str, float], wind10_ms: float | None) -> float | None:
    """Map an Open-Meteo per-point window mean to the semantic variable's value + units."""
    if variable == GHI:
        mj = daily.get(_DAILY_VAR[GHI])
        return None if mj is None else mj / 3.6              # MJ/m²/day -> kWh/m²/day
    if variable == TEMP_2M:
        return daily.get(_DAILY_VAR[TEMP_2M])                # °C
    if variable == PRECIP:
        return daily.get(_DAILY_VAR[PRECIP])                 # mm/day
    if variable == WIND_50M:
        return None if wind10_ms is None else wind10_ms * (50.0 / 10.0) ** WIND_SHEAR_ALPHA
    if variable == WIND_10M:
        return wind10_ms
    raise ValueError(f"OpenMeteoResourceProvider has no mapping for variable {variable!r}.")


class OpenMeteoResourceProvider(ResourceProvider):
    def __init__(
        self,
        archive_url: str = OPEN_METEO_ARCHIVE_URL,
        window_start: str = OPEN_METEO_WINDOW_START,
        window_end: str = OPEN_METEO_WINDOW_END,
    ) -> None:
        self.archive_url = archive_url
        self.window_start = window_start
        self.window_end = window_end

    async def get_resource_grid(
        self,
        bbox: tuple[float, float, float, float],
        resolution: float,
        variables: list[str],
    ) -> ResourceGrid:
        if not variables:
            raise ValueError("get_resource_grid requires at least one variable.")
        for var in variables:
            if var not in _DAILY_VAR and var not in _HOURLY_VAR:
                raise ValueError(f"OpenMeteoResourceProvider cannot serve variable {var!r}.")

        points, step = _point_grid(bbox, resolution, OPEN_METEO_MAX_CELLS)
        if not points:
            return ResourceGrid(bbox=bbox, resolution=step, variables=variables, cells=[])

        daily_vars = [_DAILY_VAR[v] for v in variables if v in _DAILY_VAR]
        need_wind = any(v in _HOURLY_VAR for v in variables)

        chunks = [
            points[i : i + OPEN_METEO_COORDS_PER_REQUEST]
            for i in range(0, len(points), OPEN_METEO_COORDS_PER_REQUEST)
        ]
        sem = asyncio.Semaphore(4)

        async with httpx.AsyncClient(timeout=60.0) as client:

            async def run(chunk: list[Coord]) -> list[ResourceCell]:
                async with sem:
                    return await self._fetch_chunk(client, chunk, variables, daily_vars, need_wind)

            chunk_cells = await asyncio.gather(*(run(c) for c in chunks))

        cells = [cell for group in chunk_cells for cell in group]
        cells.sort(key=lambda c: (c.lat, c.lon))
        return ResourceGrid(bbox=bbox, resolution=step, variables=variables, cells=cells)

    async def _fetch_chunk(
        self,
        client: httpx.AsyncClient,
        chunk: list[Coord],
        variables: list[str],
        daily_vars: list[str],
        need_wind: bool,
    ) -> list[ResourceCell]:
        lats = ",".join(f"{lat:.4f}" for lat, _ in chunk)
        lons = ",".join(f"{lon:.4f}" for _, lon in chunk)
        common = {
            "latitude": lats,
            "longitude": lons,
            "start_date": self.window_start,
            "end_date": self.window_end,
            "models": OPEN_METEO_MODEL,
            "timezone": "UTC",
        }

        tasks = []
        if daily_vars:
            tasks.append(self._get(client, {**common, "daily": ",".join(daily_vars)}))
        if need_wind:
            tasks.append(
                self._get(client, {**common, "hourly": "wind_speed_10m", "wind_speed_unit": "ms"})
            )
        results = await asyncio.gather(*tasks)

        # Align results back to their source block: daily first (if any), then hourly (if any).
        idx = 0
        daily_blocks = _as_list(results[idx]) if daily_vars else [None] * len(chunk)
        if daily_vars:
            idx += 1
        wind_blocks = _as_list(results[idx]) if need_wind else [None] * len(chunk)

        cells: list[ResourceCell] = []
        for (lat, lon), d_block, w_block in zip(chunk, daily_blocks, wind_blocks):
            daily_means = _means(d_block, "daily", daily_vars) if daily_vars else {}
            wind10 = _mean(_series(w_block, "hourly", "wind_speed_10m")) if need_wind else None

            values: dict[str, float] = {}
            ok = True
            for var in variables:
                v = _convert(var, daily_means, wind10)
                if v is None or math.isnan(v):
                    ok = False
                    break
                values[var] = v
            if ok:
                cells.append(ResourceCell(lat=round(lat, 4), lon=round(lon, 4), values=values))
        return cells

    async def _get(self, client: httpx.AsyncClient, params: dict) -> object:
        try:
            resp = await client.get(self.archive_url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Open-Meteo archive request failed: {exc}") from exc


# --- single-point monthly climatology (the seasonal sparkline at fine resolution) ------


async def point_monthly_climatology(
    lat: float,
    lon: float,
    variable: str,
    *,
    archive_url: str = OPEN_METEO_ARCHIVE_URL,
    window: tuple[str, str] = (OPEN_METEO_WINDOW_START, OPEN_METEO_WINDOW_END),
) -> list[float] | None:
    """12 monthly climatology means (JAN..DEC) for one semantic `variable`, in its semantic
    units, from ERA5-Land. Returns None when the point has no data (ocean / unmapped var) so the
    caller can fall back to NASA POWER. Single point -> at most one archive request."""
    if variable not in _DAILY_VAR and variable not in _HOURLY_VAR:
        return None
    start, end = window
    common = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": start,
        "end_date": end,
        "models": OPEN_METEO_MODEL,
        "timezone": "UTC",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            if variable in _DAILY_VAR:
                om_var = _DAILY_VAR[variable]
                payload = await _point_get(client, archive_url, {**common, "daily": om_var})
                block = _as_list(payload)[0]
                times = _series(block, "daily", "time")
                raw = _series(block, "daily", om_var)
                group = ("daily", om_var)
            else:
                payload = await _point_get(
                    client, archive_url, {**common, "hourly": "wind_speed_10m", "wind_speed_unit": "ms"}
                )
                block = _as_list(payload)[0]
                times = _series(block, "hourly", "time")
                raw = _series(block, "hourly", "wind_speed_10m")
                group = ("hourly", "wind_speed_10m")
    except (RuntimeError, IndexError, KeyError, TypeError):
        return None

    monthly = _monthly_means(times, raw)
    if all(m is None for m in monthly):
        return None
    # Convert each monthly mean into the variable's semantic units; fill any empty month with
    # the annual mean of valid months so the sparkline never gaps.
    valid = [m for m in monthly if m is not None]
    fill = sum(valid) / len(valid)
    return [_convert(variable, {group[1]: (m if m is not None else fill)}, m if m is not None else fill) for m in monthly]


async def _point_get(client: httpx.AsyncClient, url: str, params: dict) -> object:
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Open-Meteo archive request failed: {exc}") from exc


def _monthly_means(times: list, values: list[float | None]) -> list[float | None]:
    """Bucket an ISO-timestamped value series into 12 calendar-month means (JAN..DEC)."""
    buckets: list[list[float]] = [[] for _ in range(12)]
    for t, v in zip(times, values):
        if v is None or not isinstance(t, str) or len(t) < 7:
            continue
        try:
            month = int(t[5:7]) - 1
        except ValueError:
            continue
        if 0 <= month < 12:
            buckets[month].append(float(v))
    return [sum(b) / len(b) if b else None for b in buckets]


# --- response parsing -----------------------------------------------------------------


def _as_list(payload: object) -> list:
    """Open-Meteo returns a single object for one coord, an array for many. Normalize to a list."""
    if isinstance(payload, list):
        return payload
    return [payload]


def _series(block: object, group: str, key: str) -> list[float | None]:
    """Pull one variable's value array out of a location's `daily`/`hourly` block."""
    if not isinstance(block, dict):
        return []
    section = block.get(group)
    if not isinstance(section, dict):
        return []
    values = section.get(key)
    return values if isinstance(values, list) else []


def _mean(values: list[float | None]) -> float | None:
    """Mean over the non-null entries; None if there are none (missing / ocean)."""
    valid = [float(v) for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def _means(block: object, group: str, om_vars: list[str]) -> dict[str, float]:
    """Window mean per Open-Meteo variable for one location; omits vars with no valid data."""
    out: dict[str, float] = {}
    for var in om_vars:
        m = _mean(_series(block, group, var))
        if m is not None:
            out[var] = m
    return out


# --- point grid -----------------------------------------------------------------------


def _axis(lo: float, hi: float, step: float) -> list[float]:
    n = int(math.floor((hi - lo) / step + 1e-9))
    return [lo + i * step for i in range(n + 1)]


def _point_grid(
    bbox: tuple[float, float, float, float], resolution: float, max_cells: int
) -> tuple[list[Coord], float]:
    """Regular lat/lon point grid over the bbox at `max(resolution, native)`, coarsened until
    the cell count is within `max_cells` (cost guard). Returns the points + the step used."""
    lat_min, lon_min, lat_max, lon_max = bbox
    step = max(resolution, OPEN_METEO_NATIVE_RES_DEG)
    while True:
        lats, lons = _axis(lat_min, lat_max, step), _axis(lon_min, lon_max, step)
        if len(lats) * len(lons) <= max_cells:
            break
        step *= 1.25
    points = [(lat, lon) for lat in lats for lon in lons]
    return points, step
