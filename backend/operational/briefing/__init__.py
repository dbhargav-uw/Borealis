"""GENERIC AI briefing layer, parameterized by the vertical's metadata.

One Anthropic structured-output call. It is GIVEN the numbers, explains the
weather drivers, recommends an action with a confidence level, and NEVER invents
numbers. The system prompt uses the vertical's briefing_role (energy risk analyst
/ agronomist / cat-risk analyst / logistics dispatcher). Implemented in Phase 3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from operational.forecast.types import EnsembleForecast
from operational.risk import RiskAssessment
from verticals.base import Asset, ImpactEnsemble, VerticalMeta


class BriefingDriver(BaseModel):
    factor: str
    detail: str


class RiskBriefing(BaseModel):
    headline: str
    probability: str
    recommended_action: str
    confidence: Literal["low", "medium", "high"]
    drivers: list[BriefingDriver]


def generate_briefing(
    forecast: EnsembleForecast,
    impact: ImpactEnsemble,
    risk: RiskAssessment,
    asset: Asset,
    vertical_meta: VerticalMeta,
) -> RiskBriefing:
    """Generate a structured, vertical-aware briefing from the computed numbers.

    Implemented in Phase 3 (Anthropic SDK, structured output)."""
    raise NotImplementedError("generate_briefing lands in Phase 3.")
