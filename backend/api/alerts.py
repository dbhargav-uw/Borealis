"""GET /api/alerts — LIVE active tornado warnings + watches (NWS), cached ~15 min.

OBSERVATIONAL, real, timestamped — SEPARATE from the illustrative sim. Empty `alerts` is the normal
case (no active alert). Coverage: US + territories only. NWS requires a descriptive User-Agent.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from api.config import get_settings
from storms import AlertsResponse, build_alerts_response
from storms.cache import TTLCache

router = APIRouter()

_settings = get_settings()
_cache: TTLCache[AlertsResponse] = TTLCache(
    _settings.storms_cache_ttl_seconds,
    lambda: build_alerts_response(_settings.nws_alerts_url, _settings.nws_user_agent),
)


@router.get("/api/alerts", response_model=AlertsResponse)
async def alerts() -> AlertsResponse:
    try:
        return await _cache.get()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"NWS alerts feed failed: {exc}", "code": "alerts_provider_error"},
        )
