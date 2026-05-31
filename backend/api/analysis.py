"""GET/POST /api/analysis — the per-location RISK ANALYSIS dossier.

A single aggregation endpoint that COMPOSES the existing engines for one placed building —
it builds nothing new analytically, it only wires together:
  - the renewable-resource SuitabilityModels (energy solar/wind + agriculture crop), scored on a
    small surrounding grid so the score stays a RELATIVE comparator (never bankable yield);
  - hazard exposure: elevation-based flood read (Cesium World Terrain, sampled client-side and
    passed in), NOAA SPC tornado climatology (reusing /api/tornado-climatology), and the LIVE
    NHC/NWS feeds (reusing the cached /api/storms + /api/alerts) for current storm/alert context;
  - an Anthropic synthesis (briefing layer) producing ILLUSTRATIVE/EDUCATIONAL insurance
    considerations + a short summary, grounded ONLY in the numbers above (degrades to none).

Honesty is preserved end-to-end: resource = relative comparator; flood/tornado = illustrative,
grounded, labeled; live = real/timestamped; insurance = educational, not advice. Cached per
location so it is ONE call per placement, not per frame.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.config import get_settings
from api.tornado import TornadoClimatology, tornado_climatology
from briefing import (
    AnalysisBriefing,
    BriefingUnavailable,
    InsuranceConsideration,
    generate_analysis_briefing,
)
from registry import get_suitability_model
from resources import select_resource_provider
from resources.constants import GHI, PRECIP, TEMP_2M, WIND_50M
from scoring import score_and_rank

router = APIRouter()
logger = logging.getLogger("borealis")

# Building types that make the agriculture/crop lens relevant (intent has no 'agriculture' value).
_AGRI_TYPES = {"farm", "ranch", "vineyard", "orchard", "greenhouse", "plantation", "field"}
# Resource grid around the building: small enough to be a local comparator, >= NASA POWER's 2° min span.
_GRID_HALF_DEG = 2.0
_GRID_RESOLUTION = 0.5
_RESOURCE_NOTE = (
    "Relative comparator — long-term climatology scored across a small surrounding region, "
    "NOT bankable energy yield. Verify any real project with an on-site assessment."
)
_RESOURCE_SOURCE = "NASA POWER / Open-Meteo climatology (~0.5° regional means)"
# Live-context proximity threshold for an active tropical cyclone (great-circle km).
_STORM_NEAR_KM = 500.0
_ANALYSIS_TTL_SECONDS = 3600.0


# --- request / response models --------------------------------------------------------


class AnalysisRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    building_type: str = Field("building", max_length=60)
    intent: str = Field("general", max_length=40)
    place_name: str | None = Field(None, max_length=200)
    elevation_m: float | None = None  # terrain elevation sampled client-side (Cesium World Terrain)


class LocationInfo(BaseModel):
    place_name: str | None
    lat: float
    lon: float
    elevation_m: float | None
    terrain: str
    building_type: str
    intent: str


class ResourceLens(BaseModel):
    lens: str                       # "solar" | "wind" | "crop"
    score: float                    # 0..1, RELATIVE to the surrounding region
    raw_metric: float               # the physical value (specific yield / WPD / GDD)
    units: str
    read: str                       # plain-language "strong/weak …"
    metrics: dict[str, float]


class ResourceSection(BaseModel):
    available: bool
    region_label: str
    solar: ResourceLens | None = None
    wind: ResourceLens | None = None
    crop: ResourceLens | None = None
    note: str = _RESOURCE_NOTE
    source: str = _RESOURCE_SOURCE
    message: str | None = None


class FloodExposure(BaseModel):
    elevation_m: float | None
    low_lying: bool
    exposure: str
    scenario_note: str = (
        "Illustrative bathtub-inundation scenario over real terrain — not a hydrodynamic "
        "model or a flood prediction."
    )
    source: str = "Cesium World Terrain (elevation, sampled client-side)"


class TornadoExposure(BaseModel):
    region: str
    annual_frequency: float
    dominant_ef: int
    ef_distribution: dict[str, float]
    negligible: bool
    read: str
    scenario_note: str = (
        "Long-term regional climatology — an illustrative likelihood/intensity, not a forecast "
        "for any given day."
    )
    source: str


class LiveContext(BaseModel):
    available: bool
    nearby_storm: str | None = None
    storm_category: int | None = None
    storm_distance_km: float | None = None
    under_alert: bool = False
    alert_event: str | None = None
    summary: str = ""
    as_of: str | None = None
    source: str = "NOAA NHC active cyclones + NWS active alerts (LIVE / OBSERVED)"
    coverage: str = "NHC Atlantic + E/Central Pacific; NWS United States only."


class HazardSection(BaseModel):
    flood: FloodExposure
    tornado: TornadoExposure
    live: LiveContext


class AnalysisResponse(BaseModel):
    location: LocationInfo
    resource: ResourceSection
    hazards: HazardSection
    insurance: list[InsuranceConsideration] = Field(default_factory=list)
    summary: str | None = None
    disclaimer: str = (
        "Borealis is an illustrative weather-exploration map. Renewable-resource scores are a "
        "relative climatology comparator (not bankable yield); flood/tornado views are grounded "
        "but illustrative (not predictions); insurance items are educational considerations, NOT "
        "advice, a quote, or a financial recommendation."
    )


# --- geometry helpers (for live-feed proximity / containment) -------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting on a GeoJSON linear ring ([[lon, lat], ...])."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_geometry(lon: float, lat: float, geometry: dict | None) -> bool:
    if not geometry:
        return False
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    try:
        if gtype == "Polygon":
            return bool(coords) and _point_in_ring(lon, lat, coords[0])
        if gtype == "MultiPolygon":
            return any(poly and _point_in_ring(lon, lat, poly[0]) for poly in coords)
    except (TypeError, IndexError, KeyError):
        return False
    return False


# --- resource (reuse the SuitabilityModels at this point) -----------------------------


def _resource_read(lens: str, score: float, raw: float) -> str:
    strength = "Strong" if score >= 0.66 else "Moderate" if score >= 0.4 else "Weak"
    rel = f"{strength.lower()} relative to the surrounding region"
    if lens == "solar":
        return f"{strength} for on-site solar — {raw:.0f} kWh/kWp/yr specific yield, {rel}."
    if lens == "wind":
        return f"{strength} for on-site wind — {raw:.0f} W/m² wind power density, {rel}."
    return f"{strength} cropland agro-climate — {raw:.0f} water-adjusted GDD·yr, {rel}."


def _lens_result(
    model: Any, grid: Any, params: dict[str, Any], lens: str, metric_key: str, lat: float, lon: float
) -> ResourceLens | None:
    scores = model.score_grid(grid, params)
    units = model.metric_units(params)
    result = score_and_rank(grid, scores, None, top_n=1, metric_units=units)
    if not result.cells:
        return None
    cell = min(result.cells, key=lambda c: (c.lat - lat) ** 2 + (c.lon - lon) ** 2)
    raw = cell.metrics.get(metric_key, 0.0)
    return ResourceLens(
        lens=lens,
        score=cell.score,
        raw_metric=raw,
        units=units,
        read=_resource_read(lens, cell.score, raw),
        metrics=cell.metrics,
    )


async def _resource_section(
    lat: float, lon: float, building_type: str, settings: Any
) -> ResourceSection:
    lat_min, lat_max = max(-89.0, lat - _GRID_HALF_DEG), min(89.0, lat + _GRID_HALF_DEG)
    lon_min, lon_max = max(-179.0, lon - _GRID_HALF_DEG), min(179.0, lon + _GRID_HALF_DEG)
    bbox = (lat_min, lon_min, lat_max, lon_max)
    region_label = f"~{2 * _GRID_HALF_DEG:.0f}° around {lat:.2f}, {lon:.2f}"

    provider = select_resource_provider(
        "auto", bbox, _GRID_RESOLUTION,
        nasa_power_base_url=settings.nasa_power_base_url,
        open_meteo_archive_url=settings.open_meteo_archive_url,
        open_meteo_window=(settings.open_meteo_window_start, settings.open_meteo_window_end),
    )
    try:
        grid = await provider.get_resource_grid(bbox, _GRID_RESOLUTION, [GHI, TEMP_2M, WIND_50M, PRECIP])
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        logger.info("analysis resource grid unavailable at %.2f,%.2f: %s", lat, lon, exc)
        return ResourceSection(
            available=False, region_label=region_label,
            message="Resource climatology unavailable here (open ocean or provider error).",
        )
    if not grid.cells:
        return ResourceSection(
            available=False, region_label=region_label,
            message="No scorable climatology cells around this location (likely open ocean).",
        )

    energy = get_suitability_model("energy")
    solar = _lens_result(energy, grid, {"lens": "solar"}, "solar", "specific_yield_kwh_kwp_yr", lat, lon)
    wind = _lens_result(energy, grid, {"lens": "wind"}, "wind", "wind_power_density_wm2", lat, lon)
    crop: ResourceLens | None = None
    if building_type.lower() in _AGRI_TYPES:
        try:
            agri = get_suitability_model("agriculture")
            crop = _lens_result(agri, grid, {}, "crop", "growing_degree_days", lat, lon)
        except (KeyError, ValueError) as exc:
            logger.info("crop lens unavailable: %s", exc)

    return ResourceSection(
        available=True, region_label=region_label, solar=solar, wind=wind, crop=crop
    )


# --- hazards (reuse real data + the live feeds) ---------------------------------------


def _flood_exposure(elevation_m: float | None) -> FloodExposure:
    if elevation_m is None:
        return FloodExposure(
            elevation_m=None, low_lying=False,
            exposure="Terrain elevation was not sampled, so flood exposure is not assessed here.",
        )
    e = elevation_m
    if e < 2:
        read = "Very low-lying — high exposure to coastal storm-surge and inundation scenarios."
    elif e < 10:
        read = "Low-lying — elevated exposure to flood / inundation scenarios."
    elif e < 30:
        read = "Modest elevation — some exposure only in extreme inundation scenarios."
    else:
        read = f"Elevated terrain (~{e:.0f} m) — limited exposure to the bathtub-inundation scenario."
    return FloodExposure(elevation_m=e, low_lying=e < 10, exposure=read)


def _tornado_exposure(clim: TornadoClimatology) -> TornadoExposure:
    if clim.negligible:
        read = f"Negligible tornado risk here ({clim.region})."
    else:
        read = (
            f"EF{clim.dominant_ef}-dominant; ~{clim.annual_frequency:.2f} tornadoes/yr within "
            f"~100 km regionally ({clim.region})."
        )
    return TornadoExposure(
        region=clim.region, annual_frequency=clim.annual_frequency, dominant_ef=clim.dominant_ef,
        ef_distribution=clim.ef_distribution, negligible=clim.negligible, read=read, source=clim.source,
    )


async def _tornado_for(lat: float, lon: float) -> TornadoClimatology:
    # Reuse the existing climatology route function directly (bundled fine grid + SPC coarse fallback).
    return await tornado_climatology(lat=lat, lon=lon)


async def _live_context(lat: float, lon: float) -> LiveContext:
    # Reuse the cached /api/storms + /api/alerts loaders (real, timestamped feeds).
    from api.alerts import alerts as alerts_route
    from api.storms import storms as storms_route

    storms_res = alerts_res = None
    try:
        storms_res = await storms_route()
    except HTTPException as exc:
        logger.info("live storms unavailable for analysis: %s", exc.detail)
    try:
        alerts_res = await alerts_route()
    except HTTPException as exc:
        logger.info("live alerts unavailable for analysis: %s", exc.detail)

    if storms_res is None and alerts_res is None:
        return LiveContext(available=False, summary="Live storm/alert feeds are currently unavailable.")

    nearby_name: str | None = None
    nearby_cat: int | None = None
    nearest_km: float | None = None
    if storms_res is not None:
        for s in storms_res.storms:
            d = _haversine_km(lat, lon, s.lat, s.lon)
            if nearest_km is None or d < nearest_km:
                nearest_km, nearby_name, nearby_cat = d, s.name, s.category
        if nearest_km is not None and nearest_km > _STORM_NEAR_KM:
            nearby_name = nearby_cat = None  # closest storm is far; don't flag it as "near"

    under_alert = False
    alert_event: str | None = None
    if alerts_res is not None:
        for a in alerts_res.alerts:
            if _point_in_geometry(lon, lat, a.geometry):
                under_alert, alert_event = True, a.event
                break

    if under_alert:
        summary = f"This location is currently inside an active NWS {alert_event} polygon."
    elif nearby_name:
        summary = (
            f"Active cyclone {nearby_name} (Cat {nearby_cat}) is ~{nearest_km:.0f} km away."
            if nearby_cat
            else f"Active storm {nearby_name} is ~{nearest_km:.0f} km away."
        )
    else:
        summary = "No active NHC cyclone nearby and no NWS alert over this location right now."

    as_of = (storms_res.as_of if storms_res else None) or (alerts_res.as_of if alerts_res else None)
    return LiveContext(
        available=True, nearby_storm=nearby_name, storm_category=nearby_cat,
        storm_distance_km=round(nearest_km, 1) if (nearby_name and nearest_km is not None) else None,
        under_alert=under_alert, alert_event=alert_event, summary=summary, as_of=as_of,
    )


# --- aggregation + cache --------------------------------------------------------------

_cache: dict[str, tuple[float, AnalysisResponse]] = {}


def _cache_key(req: AnalysisRequest) -> str:
    elev = round(req.elevation_m) if req.elevation_m is not None else "na"
    return f"{req.lat:.2f},{req.lon:.2f},{req.building_type.lower()},{req.intent},{elev}"


async def _run(req: AnalysisRequest) -> AnalysisResponse:
    key = _cache_key(req)
    hit = _cache.get(key)
    if hit is not None and (time.monotonic() - hit[0]) <= _ANALYSIS_TTL_SECONDS:
        return hit[1]

    settings = get_settings()
    # Compose the existing engines concurrently; each section degrades independently.
    resource, clim, live = await asyncio.gather(
        _resource_section(req.lat, req.lon, req.building_type, settings),
        _tornado_for(req.lat, req.lon),
        _live_context(req.lat, req.lon),
    )

    terrain = (
        f"~{req.elevation_m:.0f} m elevation" if req.elevation_m is not None else "elevation unavailable"
    )
    location = LocationInfo(
        place_name=req.place_name, lat=req.lat, lon=req.lon, elevation_m=req.elevation_m,
        terrain=terrain, building_type=req.building_type, intent=req.intent,
    )
    hazards = HazardSection(
        flood=_flood_exposure(req.elevation_m), tornado=_tornado_exposure(clim), live=live
    )

    # Insurance + summary synthesis — additive; NEVER breaks the dossier (degrades to none).
    insurance: list[InsuranceConsideration] = []
    summary: str | None = None
    try:
        brief: AnalysisBriefing = await generate_analysis_briefing(
            location=location.model_dump(),
            resource=resource.model_dump(),
            hazards=hazards.model_dump(),
            model=settings.briefing_model,
            api_key=settings.anthropic_api_key,
        )
        insurance, summary = brief.insurance, brief.summary
    except BriefingUnavailable as exc:
        logger.info("analysis briefing unavailable: %s", exc)
    except Exception:  # noqa: BLE001 -- synthesis is additive, must not break the dossier
        logger.exception("analysis briefing failed")

    resp = AnalysisResponse(
        location=location, resource=resource, hazards=hazards, insurance=insurance, summary=summary
    )
    _cache[key] = (time.monotonic(), resp)
    return resp


@router.post("/api/analysis", response_model=AnalysisResponse)
async def analysis_post(req: AnalysisRequest) -> AnalysisResponse:
    return await _run(req)


@router.get("/api/analysis", response_model=AnalysisResponse)
async def analysis_get(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    building_type: str = Query("building", max_length=60),
    intent: str = Query("general", max_length=40),
    place_name: str | None = Query(None, max_length=200),
    elevation_m: float | None = Query(None),
) -> AnalysisResponse:
    return await _run(
        AnalysisRequest(
            lat=lat, lon=lon, building_type=building_type, intent=intent,
            place_name=place_name, elevation_m=elevation_m,
        )
    )
