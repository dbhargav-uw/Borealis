"""GENERIC risk math over an ImpactEnsemble. No vertical-specific logic here.

Percentile fan (P10/50/90) + threshold-crossing probabilities computed across
ensemble members. Implemented (with pytest tests) in Phase 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from verticals.base import ImpactEnsemble

__all__ = ["Threshold", "ThresholdProbability", "RiskAssessment", "assess_risk"]


class Threshold(BaseModel):
    """A decision-relevant line in the vertical's units (e.g. bid floor, frost temp)."""

    name: str
    direction: Literal["below", "above"]
    value: float


class ThresholdProbability(BaseModel):
    name: str
    prob_any: float                 # P(crossed at any hour in the window)
    prob_by_hour: list[float]       # P(crossed) per hour


class RiskAssessment(BaseModel):
    units: str
    timestamps: list[datetime]
    p10: list[float]
    p50: list[float]
    p90: list[float]
    thresholds: list[ThresholdProbability]


def assess_risk(impact: ImpactEnsemble, thresholds: list[Threshold]) -> RiskAssessment:
    """Percentiles per hour across members + P(cross threshold). Generic.

    Implemented with tests in Phase 2 (most error-prone math in the spine).
    """
    raise NotImplementedError("assess_risk lands in Phase 2 (with pytest tests).")
