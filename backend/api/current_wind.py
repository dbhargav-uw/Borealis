"""GET /api/current-wind — LIVE coarse global surface-wind grid (Open-Meteo current), cached ~15 min.

Feeds the live wind-flow layer. OBSERVATIONAL + timestamped, SEPARATE from the illustrative sim.
A COARSE, interpolated display field (a few-degree lattice) — labeled as such, never a forecast.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from api.config import get_settings
from operational.forecast.current_wind import GridWind, build_current_wind
from storms.cache import TTLCache

router = APIRouter()

_settings = get_settings()
_cache: TTLCache[GridWind] = TTLCache(
    _settings.current_wind_cache_ttl_seconds,
    lambda: build_current_wind(_settings.open_meteo_forecast_url, _settings.current_wind_resolution),
)


@router.get("/api/current-wind", response_model=GridWind)
async def current_wind() -> GridWind:
    try:
        return await _cache.get()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"Current-wind feed failed: {exc}", "code": "wind_provider_error"},
        )
