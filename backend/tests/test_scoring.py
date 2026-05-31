"""Generic scoring/ranking tests — relative normalization, MCDA weights, caveats, guards."""

from __future__ import annotations

import pytest

from resources.types import ResourceCell, ResourceGrid
from scoring import SiteWeights, score_and_rank
from verticals.base import SuitabilityScore


def _grid(coords: list[tuple[float, float]]) -> ResourceGrid:
    cells = [ResourceCell(lat=la, lon=lo, values={}) for la, lo in coords]
    return ResourceGrid(bbox=(0.0, 0.0, 10.0, 10.0), resolution=0.5, variables=[], cells=cells)


def test_normalize_and_rank() -> None:
    grid = _grid([(1, 1), (2, 2), (3, 3)])
    scores = [SuitabilityScore(raw=r, metrics={"m": r}) for r in (10.0, 20.0, 30.0)]
    res = score_and_rank(grid, scores, top_n=2, metric_units="X")
    assert res.metric_units == "X"
    assert [c.score for c in res.cells] == pytest.approx([0.0, 0.5, 1.0])
    assert len(res.ranked_sites) == 2
    assert res.ranked_sites[0].rank == 1
    assert res.ranked_sites[0].lat == 3.0 and res.ranked_sites[0].score == pytest.approx(1.0)
    assert any("RELATIVE" in c for c in res.ranked_sites[0].caveats)


def test_flat_field_is_neutral() -> None:
    res = score_and_rank(_grid([(1, 1), (2, 2)]), [SuitabilityScore(raw=5.0, metrics={})] * 2)
    assert all(c.score == 0.5 for c in res.cells)


def test_weighted_overlay() -> None:
    grid = _grid([(1, 1), (2, 2), (3, 3)])
    scores = [
        SuitabilityScore(raw=0.0, metrics={"a": 1.0, "b": 9.0}),
        SuitabilityScore(raw=0.0, metrics={"a": 5.0, "b": 5.0}),
        SuitabilityScore(raw=0.0, metrics={"a": 9.0, "b": 1.0}),
    ]
    res = score_and_rank(grid, scores, SiteWeights(weights={"a": 1.0}), top_n=1)
    assert res.ranked_sites[0].lat == 3.0  # weighting only 'a' -> highest 'a' wins


def test_guards() -> None:
    grid = _grid([(1, 1), (2, 2)])
    with pytest.raises(ValueError):  # length mismatch
        score_and_rank(grid, [SuitabilityScore(raw=1.0, metrics={})])
    with pytest.raises(ValueError):  # NaN
        score_and_rank(grid, [SuitabilityScore(raw=float("nan"), metrics={}),
                              SuitabilityScore(raw=1.0, metrics={})])
    empty = ResourceGrid(bbox=(0, 0, 10, 10), resolution=0.5, variables=[], cells=[])
    res = score_and_rank(empty, [])
    assert res.cells == [] and res.ranked_sites == []
