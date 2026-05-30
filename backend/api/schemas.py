"""Request/response models for the API layer (Phase 2: /api/assess)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from briefing import RiskBriefing
from risk import RiskAssessment, Threshold
from verticals.base import Asset


class AssessRequest(BaseModel):
    vertical: str
    asset: Asset
    thresholds: list[Threshold] = Field(default_factory=list)
    hours: int = Field(default=48, ge=1, le=168)


class ForecastSummary(BaseModel):
    """Provenance of the shared forecast INPUT (grid-snapped location, window, members)."""

    lat: float
    lon: float
    hours: int
    members: int
    variables: list[str]
    start: datetime
    end: datetime


class ImpactFan(BaseModel):
    """A thin VIEW of the RiskAssessment fan — single source of truth, no recompute."""

    units: str
    timestamps: list[datetime]
    p10: list[float]
    p50: list[float]
    p90: list[float]

    @classmethod
    def from_risk(cls, risk: RiskAssessment) -> "ImpactFan":
        return cls(
            units=risk.units,
            timestamps=risk.timestamps,
            p10=risk.p10,
            p50=risk.p50,
            p90=risk.p90,
        )


class AssessResponse(BaseModel):
    forecast_summary: ForecastSummary
    impact_fan: ImpactFan
    risk: RiskAssessment
    briefing: RiskBriefing | None = None  # populated in Phase 3
