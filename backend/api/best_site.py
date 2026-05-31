"""POST /api/best-site — "find the best place in a region to build X, then build there".

COMPOSES the existing engines (no new analytics): the Anthropic parse extracts the region bbox +
objective; a grid over the region is scored with the relevant SuitabilityModel (reuse
score_and_rank), the land/water mask drops ocean, and per-cell HAZARD PENALTIES (tornado from NOAA
SPC climatology, flood from coarse terrain elevation via Open-Meteo) are blended in per the
objective. The top-scoring valid cell wins; top-N candidates + an LLM "why here" explanation are
returned. The frontend places the detailed building at the winner and opens the dossier.

HONESTY: this is "best WITHIN this region by the stated criteria, from available climate + hazard
data" — a RELATIVE comparator, NOT a bankable siting recommendation (no grid, land, permitting, or
cost). The ranked candidates + scores are returned so the choice is transparent. Cached per query.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.config import get_settings
from api.tornado import tornado_climatology
from briefing import (
    BestSiteExplanation,
    BestSiteQuery,
    BriefingUnavailable,
    generate_best_site_explanation,
    parse_best_site_query,
)
from constraints import apply_land_mask
from registry import get_suitability_model
from resources import select_resource_provider
from resources.elevation import fetch_elevations
from scoring import score_and_rank

router = APIRouter()
logger = logging.getLogger("borealis")

_RESOLUTION = 1.0  # coarse region grid — a one-time comparator, keeps cell + fan-out count modest
_HAZARD_LAMBDA = 0.5  # how strongly hazard penalizes a renewable/crop objective
_TOP_N = 5
_MIN_SPAN, _MAX_SPAN = 2.0, 10.0

# objective -> (vertical, score params, the raw metric to surface). hazard_min uses a benign climate base.
_OBJECTIVE = {
    "solar": ("energy", {"lens": "solar"}, "specific_yield_kwh_kwp_yr", "kWh/kWp/yr"),
    "wind": ("energy", {"lens": "wind"}, "wind_power_density_wm2", "W/m²"),
    "crop": ("agriculture", {}, "growing_degree_days", "GDD·yr"),
    "hazard_min": ("energy", {"lens": "solar"}, "specific_yield_kwh_kwp_yr", "kWh/kWp/yr"),
}


class BestSiteRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=400)


class SiteScore(BaseModel):
    lat: float
    lon: float
    score: float          # final combined score (0..1), objective-weighted with hazard penalties
    suitability: float    # relative climate suitability (0..1) within the region
    metrics: dict[str, float]


class BestSiteResponse(BaseModel):
    best_site: SiteScore | None
    top_candidates: list[SiteScore]
    region_bbox: dict[str, float]
    region_label: str
    building_type: str
    objective: str
    metric_units: str
    explanation: BestSiteExplanation | None = None
    message: str | None = None
    disclaimer: str = (
        "Best WITHIN this region by the stated criteria, from available climate + hazard climatology "
        "— a RELATIVE comparator, NOT a bankable siting recommendation (ignores grid connection, land "
        "ownership, permitting, and cost). Ranked candidates + scores are shown for transparency."
    )


def _clamp_axis(lo: float, hi: float, bound: float) -> tuple[float, float]:
    lo, hi = min(lo, hi), max(lo, hi)
    center = (lo + hi) / 2.0
    span = max(_MIN_SPAN, min(_MAX_SPAN, hi - lo))
    new_lo, new_hi = center - span / 2.0, center + span / 2.0
    if new_lo < -bound:
        new_lo, new_hi = -bound, -bound + span
    if new_hi > bound:
        new_lo, new_hi = bound - span, bound
    return new_lo, new_hi


def _flood_penalty(elev: float | None) -> float:
    if elev is None:
        return 0.0  # unknown elevation → neutral (no flood penalty)
    if elev < 2:
        return 1.0
    if elev < 10:
        return 0.6
    if elev < 30:
        return 0.3
    if elev < 100:
        return 0.1
    return 0.03


def _tornado_penalty(annual_freq: float) -> float:
    return min(1.0, annual_freq / 1.5)  # ~1.0 in Tornado Alley, ~0 outside


_cache: dict[str, BestSiteResponse] = {}


async def _run(query: str) -> BestSiteResponse:
    key = query.strip().lower()
    if key in _cache:
        return _cache[key]

    settings = get_settings()
    try:
        q: BestSiteQuery = await parse_best_site_query(
            query=query, model=settings.briefing_model, api_key=settings.anthropic_api_key
        )
    except BriefingUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"Site search needs an Anthropic API key. {exc}", "code": "llm_unavailable"},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail={"error": f"Query parsing failed: {exc}", "code": "best_site_failed"})

    lat_min, lat_max = _clamp_axis(q.lat_min, q.lat_max, 90.0)
    lon_min, lon_max = _clamp_axis(q.lon_min, q.lon_max, 180.0)
    bbox = (lat_min, lon_min, lat_max, lon_max)
    region_bbox = {"lat_min": lat_min, "lon_min": lon_min, "lat_max": lat_max, "lon_max": lon_max}
    vertical, params, metric_key, units = _OBJECTIVE.get(q.objective, _OBJECTIVE["hazard_min"])

    # 1. Score a region grid with the objective's SuitabilityModel (NASA POWER — coarse, global, fast).
    model = get_suitability_model(vertical)
    provider = select_resource_provider("nasa_power", bbox, _RESOLUTION, nasa_power_base_url=settings.nasa_power_base_url)
    try:
        grid = await provider.get_resource_grid(bbox, _RESOLUTION, model.required_variables)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail={"error": f"Resource provider failed: {exc}", "code": "resource_provider_error"}
        )
    grid = apply_land_mask(grid)  # onshore only — drop ocean cells
    if not grid.cells:
        resp = BestSiteResponse(
            best_site=None, top_candidates=[], region_bbox=region_bbox, region_label=q.region_label,
            building_type=q.building_type, objective=q.objective, metric_units=units,
            message="No scorable land cells in this region.",
        )
        _cache[key] = resp
        return resp
    try:
        scores = model.score_grid(grid, params)
        result = score_and_rank(grid, scores, None, top_n=len(grid.cells), metric_units=units)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc), "code": "invalid_scoring"})

    # 2. Per-cell HAZARD penalties: tornado (SPC, local, cheap) + flood (one batched elevation call).
    cells = result.cells
    elevations = await fetch_elevations([(c.lat, c.lon) for c in cells])
    torn = await asyncio.gather(*(tornado_climatology(lat=c.lat, lon=c.lon) for c in cells))
    w_t = 1.0 if q.avoid_tornado else 0.5
    w_f = 1.0 if q.avoid_flood else 0.5

    scored: list[SiteScore] = []
    for c, elev, t in zip(cells, elevations, torn):
        t_pen = _tornado_penalty(t.annual_frequency)
        f_pen = _flood_penalty(elev)
        hazard_pen = min(1.0, (w_t * t_pen + w_f * f_pen) / (w_t + w_f))
        if q.objective == "hazard_min":
            final = 0.85 * (1.0 - hazard_pen) + 0.15 * c.score
        else:
            final = max(0.0, c.score - _HAZARD_LAMBDA * hazard_pen)
        metrics = dict(c.metrics)
        metrics["suitability_score"] = round(c.score, 4)
        metrics["tornado_annual_frequency"] = round(t.annual_frequency, 3)
        metrics["tornado_penalty"] = round(t_pen, 3)
        metrics["flood_penalty"] = round(f_pen, 3)
        if elev is not None:
            metrics["elevation_m"] = round(elev, 1)
        metrics["final_score"] = round(final, 4)
        scored.append(SiteScore(lat=c.lat, lon=c.lon, score=round(final, 4), suitability=round(c.score, 4), metrics=metrics))

    scored.sort(key=lambda s: s.score, reverse=True)
    best = scored[0]
    candidates = scored[:_TOP_N]

    # 3. "Why here" explanation (additive; degrades to None without a key).
    explanation: BestSiteExplanation | None = None
    try:
        explanation = await generate_best_site_explanation(
            objective=q.objective,
            region_label=q.region_label,
            best=best.model_dump(),
            candidates=[c.model_dump() for c in candidates[1:]],
            model=settings.briefing_model,
            api_key=settings.anthropic_api_key,
        )
    except BriefingUnavailable as exc:
        logger.info("best-site explanation unavailable: %s", exc)
    except Exception:  # noqa: BLE001 -- explanation is additive, must not break the result
        logger.exception("best-site explanation failed")

    resp = BestSiteResponse(
        best_site=best, top_candidates=candidates, region_bbox=region_bbox, region_label=q.region_label,
        building_type=q.building_type, objective=q.objective, metric_units=units, explanation=explanation,
    )
    _cache[key] = resp
    return resp


@router.post("/api/best-site", response_model=BestSiteResponse)
async def best_site(req: BestSiteRequest) -> BestSiteResponse:
    return await _run(req.query)
