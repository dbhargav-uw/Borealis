"""GENERIC site scoring + ranking (MCDA). No vertical-specific logic — it operates only
on raw SuitabilityScores + a ResourceGrid, the way the (now operational) risk layer
operated only on an ImpactEnsemble.

Per-metric min-max normalization ACROSS the queried region (so scores are RELATIVE),
optional weighted overlay, descending rank, top-N with honest caveats. Rejects
NaN / empty / length-mismatch like the old assess_risk.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from resources.types import ResourceGrid
from verticals.base import SuitabilityScore


class SiteWeights(BaseModel):
    """MCDA weights over named metrics. Empty -> rank on the model's primary raw value."""

    weights: dict[str, float] = Field(default_factory=dict)


class CellScore(BaseModel):
    lat: float
    lon: float
    score: float                  # 0..1, RELATIVE to the queried region
    metrics: dict[str, float]


class RankedSite(BaseModel):
    rank: int                     # 1 = best in the region
    lat: float
    lon: float
    score: float
    metrics: dict[str, float]
    caveats: list[str]


class SuitabilityResult(BaseModel):
    metric_units: str
    cells: list[CellScore]
    ranked_sites: list[RankedSite]


def _minmax(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.5] * len(values)   # flat field -> neutral 0.5 (avoid divide-by-zero)
    return [(v - lo) / (hi - lo) for v in values]


def score_and_rank(
    grid: ResourceGrid,
    scores: list[SuitabilityScore],
    weights: SiteWeights | None = None,
    top_n: int = 5,
    metric_units: str = "",
) -> SuitabilityResult:
    if len(scores) != len(grid.cells):
        raise ValueError(
            f"scores ({len(scores)}) != grid cells ({len(grid.cells)})."
        )
    n = len(scores)
    if n == 0:
        return SuitabilityResult(metric_units=metric_units, cells=[], ranked_sites=[])

    raws = [s.raw for s in scores]
    if any(math.isnan(r) for r in raws):
        raise ValueError("SuitabilityScore.raw contains NaN; clean upstream.")

    active = weights.weights if (weights and weights.weights) else {}
    if active:
        norm_cols: dict[str, list[float]] = {}
        for metric in active:
            col = [s.metrics.get(metric, math.nan) for s in scores]
            if any(math.isnan(c) for c in col):
                raise ValueError(f"weight references metric '{metric}' missing in some cells.")
            norm_cols[metric] = _minmax(col)
        total = sum(active.values()) or 1.0
        cell_scores = [
            sum(active[m] * norm_cols[m][i] for m in active) / total for i in range(n)
        ]
    else:
        cell_scores = _minmax(raws)

    cells = [
        CellScore(lat=c.lat, lon=c.lon, score=cell_scores[i], metrics=scores[i].metrics)
        for i, c in enumerate(grid.cells)
    ]
    order = sorted(range(n), key=lambda i: cell_scores[i], reverse=True)[: max(0, top_n)]
    ranked = [
        RankedSite(
            rank=rank,
            lat=grid.cells[i].lat,
            lon=grid.cells[i].lon,
            score=cell_scores[i],
            metrics=scores[i].metrics,
            caveats=_caveats(grid, grid.cells[i].lat, grid.cells[i].lon),
        )
        for rank, i in enumerate(order, start=1)
    ]
    return SuitabilityResult(metric_units=metric_units, cells=cells, ranked_sites=ranked)


def _caveats(grid: ResourceGrid, lat: float, lon: float) -> list[str]:
    caveats = [
        "Suitability is RELATIVE to the queried region (min-max normalized), not absolute.",
        f"Long-term climatology (NASA POWER, ~{grid.resolution}° grid) — a ranking "
        "comparator, NOT bankable yield; verify any candidate with a real site assessment.",
    ]
    lat_min, lon_min, lat_max, lon_max = grid.bbox
    edge = min(lat - lat_min, lat_max - lat, lon - lon_min, lon_max - lon)
    if edge < grid.resolution:
        caveats.append("Near the region edge — boundary scores are less stable.")
    return caveats
