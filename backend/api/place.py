"""POST /api/place — parse a natural-language building request into a structured placement.

query (e.g. "a coastal hospital in Miami") -> { label, place_name, building_type, intent }. The frontend
geocodes place_name via the Cesium ion geocoder and places a building; intent selects the contextual layer
(suitability lens or a flood/tornado hazard). Needs an Anthropic key; degrades to 503 without one.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.config import get_settings
from briefing import (
    BriefingUnavailable,
    BuildingQuery,
    HazardBriefing,
    generate_hazard_briefing,
    parse_building_query,
)

router = APIRouter()
logger = logging.getLogger("borealis")


class PlaceRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)


class PlaceResponse(BaseModel):
    label: str
    place_name: str
    building_type: str
    intent: str
    # richer SPEC for glTF model selection + sizing (nullable; frontend falls back to per-type defaults)
    approx_floors: int | None = None
    height_m: float | None = None
    footprint_m: float | None = None
    style: str | None = None
    roof_type: str | None = None
    features: list[str] = []


@router.post("/api/place", response_model=PlaceResponse)
async def place(req: PlaceRequest) -> PlaceResponse:
    settings = get_settings()
    try:
        q: BuildingQuery = await parse_building_query(
            query=req.query, model=settings.briefing_model, api_key=settings.anthropic_api_key
        )
    except BriefingUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"Building placement needs an Anthropic API key. {exc}", "code": "llm_unavailable"},
        )
    except Exception as exc:  # noqa: BLE001 -- surface any parse failure as a typed 502
        raise HTTPException(
            status_code=502, detail={"error": f"Query parsing failed: {exc}", "code": "place_failed"}
        )
    return PlaceResponse(
        label=q.label, place_name=q.place_name, building_type=q.building_type, intent=q.intent,
        approx_floors=q.approx_floors, height_m=q.height_m, footprint_m=q.footprint_m,
        style=q.style, roof_type=q.roof_type, features=q.features,
    )


# --- POST /api/hazard-briefing — short AI exposure explanation for a simulated flood/tornado -------


class HazardBriefingRequest(BaseModel):
    kind: Literal["flood", "tornado"]
    building_label: str = Field(..., max_length=200)
    place_name: str = Field(..., max_length=200)
    scenario: dict[str, Any] = Field(default_factory=dict)  # the real numbers (depth / EF / frequency / source)


class HazardBriefingResponse(BaseModel):
    briefing: HazardBriefing | None = None  # null without a key — the hazard view is the core product


@router.post("/api/hazard-briefing", response_model=HazardBriefingResponse)
async def hazard_briefing(req: HazardBriefingRequest) -> HazardBriefingResponse:
    settings = get_settings()
    try:
        briefing = await generate_hazard_briefing(
            kind=req.kind,
            building_label=req.building_label,
            place_name=req.place_name,
            scenario=req.scenario,
            model=settings.briefing_model,
            api_key=settings.anthropic_api_key,
        )
        return HazardBriefingResponse(briefing=briefing)
    except BriefingUnavailable as exc:
        logger.info("hazard briefing unavailable: %s", exc)
        return HazardBriefingResponse(briefing=None)
    except Exception:  # noqa: BLE001 -- briefing is additive, never break the hazard view
        logger.exception("hazard briefing failed")
        return HazardBriefingResponse(briefing=None)
