"""GET /api/storms — LIVE active tropical cyclones (NOAA NHC), cached ~15 min.

OBSERVATIONAL, real, timestamped — a SEPARATE category from the illustrative building-level hazard
sim. Empty `storms` is the normal case (off-season). Coverage: Atlantic + E/Central Pacific only.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from api.config import get_settings
from storms import StormsResponse, build_storms_response
from storms.cache import TTLCache

router = APIRouter()

_settings = get_settings()
_cache: TTLCache[StormsResponse] = TTLCache(
    _settings.storms_cache_ttl_seconds,
    lambda: build_storms_response(_settings.nhc_current_storms_url),
)


@router.get("/api/storms", response_model=StormsResponse)
async def storms() -> StormsResponse:
    try:
        return await _cache.get()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"NHC storms feed failed: {exc}", "code": "storms_provider_error"},
        )
