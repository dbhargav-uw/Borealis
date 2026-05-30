"""POST /api/suitability — the site-selection spine wired end-to-end.

vertical -> SuitabilityModel; region -> resource grid (climatology, async) ->
model.score_grid (per cell) -> generic score_and_rank -> heatmap cells + ranked sites.
The route stays vertical-agnostic; everything energy-specific lives in verticals/energy/.
The "why this site" briefing wires into the `briefing` field in P4.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from api.config import get_settings
from registry import get_suitability_model, registered_suitability_verticals
from resources import get_resource_provider
from scoring import CellScore, RankedSite, SiteWeights, score_and_rank

router = APIRouter()


class BBox(BaseModel):
    lat_min: float = Field(..., ge=-90, le=90)
    lon_min: float = Field(..., ge=-180, le=180)
    lat_max: float = Field(..., ge=-90, le=90)
    lon_max: float = Field(..., ge=-180, le=180)

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if not (self.lat_min < self.lat_max and self.lon_min < self.lon_max):
            raise ValueError("require lat_min < lat_max and lon_min < lon_max")
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.lat_min, self.lon_min, self.lat_max, self.lon_max)


class SuitabilityRequest(BaseModel):
    vertical: str
    region: BBox
    resolution: float = Field(0.5, ge=0.5, le=2.0)
    params: dict = Field(default_factory=dict)          # e.g. {"lens": "solar"}
    weights: dict[str, float] | None = None             # MCDA metric weights (optional)
    top_n: int = Field(5, ge=1, le=50)


class SuitabilityResponse(BaseModel):
    region: BBox
    resolution: float
    vertical: str
    metric_units: str
    n_cells: int
    cells: list[CellScore]
    ranked_sites: list[RankedSite]
    briefing: dict | None = None                        # SiteBriefing lands in P4


@router.post("/api/suitability", response_model=SuitabilityResponse)
async def suitability(req: SuitabilityRequest) -> SuitabilityResponse:
    # 1. Resolve the vertical's SuitabilityModel (unknown -> 404).
    try:
        model = get_suitability_model(req.vertical)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Unknown vertical '{req.vertical}'.",
                "code": "unknown_vertical",
                "registered": registered_suitability_verticals(),
            },
        )

    # 2. Shared resource INPUT (async). Variables = this model's required_variables.
    settings = get_settings()
    provider = get_resource_provider(settings.nasa_power_base_url)
    try:
        grid = await provider.get_resource_grid(
            req.region.as_tuple(), req.resolution, model.required_variables
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"Resource provider failed: {exc}", "code": "resource_provider_error"},
        )

    # 3. Per-cell suitability (sync) -> 4. generic normalize + rank. Bad params -> 422.
    try:
        scores = model.score_grid(grid, req.params)
        units = model.metric_units(req.params)
        weights = SiteWeights(weights=req.weights) if req.weights else None
        result = score_and_rank(grid, scores, weights, req.top_n, metric_units=units)
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=422, detail={"error": str(exc), "code": "invalid_suitability"}
        )

    return SuitabilityResponse(
        region=req.region,
        resolution=grid.resolution,
        vertical=req.vertical,
        metric_units=result.metric_units,
        n_cells=len(result.cells),
        cells=result.cells,
        ranked_sites=result.ranked_sites,
        briefing=None,
    )
