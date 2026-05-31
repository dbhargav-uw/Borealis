"""POST /api/suitability — the site-selection spine wired end-to-end.

vertical -> SuitabilityModel; region -> resource grid (climatology, async) ->
model.score_grid (per cell) -> generic score_and_rank -> heatmap cells + ranked sites.
The route stays vertical-agnostic; everything energy-specific lives in verticals/energy/.
The "why this site" briefing wires into the `briefing` field in P4.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from api.config import get_settings
from briefing import (
    BriefingUnavailable,
    GlobeQuery,
    SiteBriefing,
    generate_site_briefing,
    parse_globe_query,
)
from constraints import apply_land_mask
from registry import get_suitability_model, registered_suitability_verticals
from resources import get_resource_provider
from scoring import CellScore, RankedSite, SiteWeights, score_and_rank

router = APIRouter()
logger = logging.getLogger("borealis")


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
    include_briefing: bool = False                      # generate the "why this site" briefing
    region_label: str | None = None                     # human label for the region (briefing)
    land_only: bool = True                               # drop ocean cells (onshore siting)


class SuitabilityResponse(BaseModel):
    region: BBox
    resolution: float
    vertical: str
    metric_units: str
    n_cells: int
    cells: list[CellScore]
    ranked_sites: list[RankedSite]
    briefing: SiteBriefing | None = None


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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "invalid_region"})
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": f"Resource provider failed: {exc}", "code": "resource_provider_error"},
        )
    if req.land_only:
        grid = apply_land_mask(grid)

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

    # 5. Optional "why this site" briefing — additive; NEVER breaks the suitability result.
    briefing: SiteBriefing | None = None
    if req.include_briefing and result.ranked_sites:
        label = req.region_label or (
            f"{req.region.lat_min:.0f}–{req.region.lat_max:.0f}°N, "
            f"{req.region.lon_min:.0f}–{req.region.lon_max:.0f}°E"
        )
        try:
            briefing = await generate_site_briefing(
                region_label=label,
                lens=str(req.params.get("lens", "")),
                metric_units=result.metric_units,
                ranked_sites=[rs.model_dump() for rs in result.ranked_sites],
                briefing_role=model.meta().briefing_role,
                model=settings.briefing_model,
                api_key=settings.anthropic_api_key,
            )
        except BriefingUnavailable as exc:
            logger.info("briefing unavailable: %s", exc)
        except Exception:  # noqa: BLE001 -- briefing is additive, must not break the response
            logger.exception("briefing generation failed")

    return SuitabilityResponse(
        region=req.region,
        resolution=grid.resolution,
        vertical=req.vertical,
        metric_units=result.metric_units,
        n_cells=len(result.cells),
        cells=result.cells,
        ranked_sites=result.ranked_sites,
        briefing=briefing,
    )


# --- POST /api/ask — natural-language "ask the globe" -> region + lens -----------------


class AskRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)


class AskResponse(BaseModel):
    label: str
    region: BBox
    lens: str


def _clamp_axis(
    lo: float, hi: float, bound: float, min_span: float = 2.0, max_span: float = 10.0
) -> tuple[float, float]:
    center = (lo + hi) / 2.0
    span = max(min_span, min(max_span, hi - lo))
    new_lo, new_hi = center - span / 2.0, center + span / 2.0
    if new_lo < -bound:
        new_lo, new_hi = -bound, -bound + span
    if new_hi > bound:
        new_lo, new_hi = bound - span, bound
    return new_lo, new_hi


@router.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    """Parse a natural-language siting question into a region bbox + lens (LLM). The
    frontend then calls /api/suitability with the result. Needs an Anthropic key."""
    settings = get_settings()
    try:
        q: GlobeQuery = await parse_globe_query(
            query=req.query, model=settings.briefing_model, api_key=settings.anthropic_api_key
        )
    except BriefingUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"Natural-language search needs an Anthropic API key. {exc}", "code": "llm_unavailable"},
        )
    except Exception as exc:  # noqa: BLE001 -- surface any parse failure as a typed 502
        raise HTTPException(
            status_code=502, detail={"error": f"Query parsing failed: {exc}", "code": "ask_failed"}
        )

    lat_min, lat_max = _clamp_axis(min(q.lat_min, q.lat_max), max(q.lat_min, q.lat_max), 90.0, max_span=14.0)
    lon_min, lon_max = _clamp_axis(min(q.lon_min, q.lon_max), max(q.lon_min, q.lon_max), 180.0, max_span=14.0)
    return AskResponse(
        label=q.label,
        region=BBox(lat_min=lat_min, lon_min=lon_min, lat_max=lat_max, lon_max=lon_max),
        lens=q.lens,
    )
