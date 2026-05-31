"""POST /api/assess — the generic spine wired end-to-end.

vertical -> ImpactModel; shared ensemble forecast (async) -> model.apply (sync) ->
generic assess_risk (sync) -> typed response. Briefing is deferred to Phase 3 (null).
The route stays vertical-agnostic: everything energy-specific lives in verticals/energy/.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from api.config import get_settings
from operational.forecast import get_provider
from operational.risk import assess_risk
from operational.schemas import AssessRequest, AssessResponse, ForecastSummary, ImpactFan
from registry import get_impact_model, registered_verticals

router = APIRouter()


@router.post("/api/operational/assess", response_model=AssessResponse)
async def assess(req: AssessRequest) -> AssessResponse:
    # 1. Resolve the vertical's ImpactModel (unknown -> 404, typed JSON).
    try:
        model = get_impact_model(req.vertical)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Unknown vertical '{req.vertical}'.",
                "code": "unknown_vertical",
                "registered": registered_verticals(),
            },
        )

    # 2. Shared forecast INPUT (async). Variables = this model's required_variables.
    settings = get_settings()
    provider = get_provider(settings.open_meteo_base_url)
    try:
        forecast = await provider.get_ensemble_forecast(
            req.asset.lat, req.asset.lon, req.hours, model.required_variables
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"Forecast provider failed: {exc}",
                "code": "forecast_provider_error",
            },
        )

    # 3. Vertical impact (sync) -> 4. generic risk (sync). Bad params/degenerate -> 422.
    try:
        impact = model.apply(forecast, req.asset)
        risk = assess_risk(impact, req.thresholds)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail={"error": str(exc), "code": "invalid_impact"}
        )

    # 5. Assemble. impact_fan is projected from risk (one source of truth). briefing -> Phase 3.
    return AssessResponse(
        forecast_summary=ForecastSummary(
            lat=forecast.lat,
            lon=forecast.lon,
            hours=forecast.hours,
            members=forecast.members,
            variables=sorted(forecast.variables.keys()),
            start=forecast.timestamps[0],
            end=forecast.timestamps[-1],
        ),
        impact_fan=ImpactFan.from_risk(risk),
        risk=risk,
        briefing=None,
    )
