"""GET /api/seasonal — a single site's 12-month climatology profile (NASA POWER point endpoint).

Powers the detail panel's "seasonal profile" sparkline: once you've picked a candidate site, see
how its resource varies month-to-month (the spread the annual mean hides). Climatology, so it's a
typical year, not a forecast — same honest framing as the rest of the product.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.config import get_settings
from resources.constants import NASA_POWER_POINT_URL, POWER_COMMUNITY, POWER_FILL
from resources.openmeteo import point_monthly_climatology

router = APIRouter()

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# A month at/below POWER's -999 fill is missing data; threshold a hair above it.
POWER_PRESENT_THRESHOLD = POWER_FILL + 1.0

# Display variables we expose for the seasonal sparkline -> their physical units.
SEASONAL_UNITS: dict[str, str] = {
    "ALLSKY_SFC_SW_DWN": "kWh/m²/day",
    "WS50M": "m/s",
    "WS10M": "m/s",
    "T2M": "°C",
    "PRECTOTCORR": "mm/day",
}


class SeasonalResponse(BaseModel):
    variable: str
    units: str
    months: list[float]  # 12 monthly climatology means, JAN..DEC


def _clean(months: list[float]) -> list[float]:
    """Replace POWER's -999 fill (e.g. an offshore point) with the mean of the valid months so
    the sparkline never spikes; if every month is fill, return zeros."""
    valid = [m for m in months if m > POWER_PRESENT_THRESHOLD]
    if not valid:
        return [0.0] * len(months)
    fill = sum(valid) / len(valid)
    return [m if m > POWER_PRESENT_THRESHOLD else fill for m in months]


@router.get("/api/seasonal", response_model=SeasonalResponse)
async def seasonal(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    variable: str = Query(..., min_length=2, max_length=40),
) -> SeasonalResponse:
    if variable not in SEASONAL_UNITS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"Unsupported variable '{variable}'.",
                "code": "invalid_variable",
                "supported": sorted(SEASONAL_UNITS),
            },
        )

    # Prefer the FINE ERA5-Land climatology (matches the high-res grid); fall back to NASA
    # POWER when the point has no Open-Meteo data (ocean / land-only model) or the call fails.
    settings = get_settings()
    om_months = await point_monthly_climatology(
        lat,
        lon,
        variable,
        archive_url=settings.open_meteo_archive_url,
        window=(settings.open_meteo_window_start, settings.open_meteo_window_end),
    )
    if om_months is not None:
        return SeasonalResponse(variable=variable, units=SEASONAL_UNITS[variable], months=om_months)

    params = {
        "parameters": variable,
        "community": POWER_COMMUNITY,
        "latitude": lat,
        "longitude": lon,
        "format": "JSON",
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(NASA_POWER_POINT_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"NASA POWER request failed: {exc}", "code": "resource_provider_error"},
        )
    try:
        param = data["properties"]["parameter"][variable]
        months = [float(param[m]) for m in MONTHS]
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"Malformed NASA POWER response: {exc}", "code": "resource_provider_error"},
        )
    return SeasonalResponse(variable=variable, units=SEASONAL_UNITS[variable], months=_clean(months))
