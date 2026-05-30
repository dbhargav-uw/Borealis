"""GENERIC risk math over an ImpactEnsemble. No vertical-specific logic here.

Percentile fan (P10/50/90) + threshold-crossing probabilities computed across
ensemble members. Implemented (with pytest tests) in Phase 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import numpy as np
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
    """Percentile fan (P10/P50/P90) + threshold-crossing probabilities across members.

    GENERIC: operates only on impact.series ([member N][hour H]) plus the vertical's
    units/timestamps — no vertical-specific logic. Per hour, percentiles are taken across
    members. For a Threshold, prob_by_hour[h] is the fraction of members crossing at hour
    h (STRICT: ``<`` for "below", ``>`` for "above"); prob_any is the fraction of members
    crossing at ANY hour in the window (per-member OR -> always >= max(prob_by_hour)).

    Rejects NaN / ragged / empty input: a NaN compares False and would silently undercount
    crossings, hiding forecast data gaps. The forecast provider owns cleaning.
    """
    series = impact.series
    n_members = len(series)
    if n_members == 0:
        raise ValueError("ImpactEnsemble has no members; cannot compute percentiles.")

    hour_counts = {len(row) for row in series}
    if len(hour_counts) > 1:
        raise ValueError(
            f"Ragged ImpactEnsemble.series: members have differing hour counts {sorted(hour_counts)}."
        )

    arr = np.asarray(series, dtype=float)  # (N, H)
    n_hours = arr.shape[1] if arr.ndim == 2 else 0

    if n_hours != len(impact.timestamps):
        raise ValueError(
            f"series hour count {n_hours} != timestamps {len(impact.timestamps)}."
        )

    if np.isnan(arr).any():
        raise ValueError(
            "ImpactEnsemble contains NaN; clean/forward-fill in the forecast provider "
            "before risk math."
        )

    if n_hours == 0:  # valid degenerate window: members present, zero hours
        return RiskAssessment(
            units=impact.units,
            timestamps=impact.timestamps,
            p10=[],
            p50=[],
            p90=[],
            thresholds=[
                ThresholdProbability(name=t.name, prob_any=0.0, prob_by_hour=[])
                for t in thresholds
            ],
        )

    p10, p50, p90 = np.percentile(arr, [10.0, 50.0, 90.0], axis=0, method="linear")

    tps: list[ThresholdProbability] = []
    for t in thresholds:
        mask = (arr < t.value) if t.direction == "below" else (arr > t.value)  # STRICT
        prob_by_hour = mask.mean(axis=0)            # fraction crossing AT each hour
        prob_any = float(mask.any(axis=1).mean())   # fraction crossing at ANY hour
        tps.append(
            ThresholdProbability(
                name=t.name, prob_any=prob_any, prob_by_hour=prob_by_hour.tolist()
            )
        )

    return RiskAssessment(
        units=impact.units,
        timestamps=impact.timestamps,
        p10=p10.tolist(),
        p50=p50.tolist(),
        p90=p90.tolist(),
        thresholds=tps,
    )
