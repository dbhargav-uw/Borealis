"""Generic risk-math tests: hand-built ensembles so percentiles + probs are checkable."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from operational.risk import Threshold, assess_risk
from verticals.base import ImpactEnsemble


def _ts(n: int) -> list[datetime]:
    base = datetime(2026, 5, 30, 0, 0)
    return [base + timedelta(hours=i) for i in range(n)]


def test_percentiles_known_values() -> None:
    # 11 members 0..100, 1 hour. numpy linear: P10=10, P50=50, P90=90 exactly.
    series = [[float(v)] for v in range(0, 101, 10)]
    r = assess_risk(ImpactEnsemble(units="MW", timestamps=_ts(1), series=series), [])
    assert r.units == "MW"
    assert r.p10 == pytest.approx([10.0])
    assert r.p50 == pytest.approx([50.0])
    assert r.p90 == pytest.approx([90.0])
    assert r.thresholds == []


def test_threshold_below() -> None:
    # 4 members x 3 hours, below 5.0 (strict).
    # h0 {m2}=0.25  h1 {m0,m2}=0.50  h2 {m0,m2}=0.50 ; prob_any {m0,m2}=0.50
    series = [[10.0, 4.0, 3.0], [10.0, 6.0, 10.0], [2.0, 2.0, 2.0], [10.0, 10.0, 10.0]]
    r = assess_risk(
        ImpactEnsemble(units="MW", timestamps=_ts(3), series=series),
        [Threshold(name="below_floor", direction="below", value=5.0)],
    )
    tp = r.thresholds[0]
    assert tp.name == "below_floor"
    assert tp.prob_by_hour == pytest.approx([0.25, 0.50, 0.50])
    assert tp.prob_any == pytest.approx(0.50)
    assert tp.prob_any >= max(tp.prob_by_hour)  # OR-over-hours invariant


def test_threshold_above_strict() -> None:
    # ==value is NOT a cross. m0[5,8] m1[5,4]; above 5: h0=0.0, h1={m0}=0.5; prob_any=0.5
    series = [[5.0, 8.0], [5.0, 4.0]]
    r = assess_risk(
        ImpactEnsemble(units="gust_kt", timestamps=_ts(2), series=series),
        [Threshold(name="gust_trig", direction="above", value=5.0)],
    )
    tp = r.thresholds[0]
    assert tp.prob_by_hour == pytest.approx([0.0, 0.5])
    assert tp.prob_any == pytest.approx(0.5)


def test_single_member_ok() -> None:
    r = assess_risk(ImpactEnsemble(units="MW", timestamps=_ts(2), series=[[3.0, 7.0]]), [])
    assert r.p10 == pytest.approx([3.0, 7.0])
    assert r.p50 == pytest.approx([3.0, 7.0])
    assert r.p90 == pytest.approx([3.0, 7.0])


def test_edge_cases_raise() -> None:
    with pytest.raises(ValueError):  # empty members
        assess_risk(ImpactEnsemble(units="MW", timestamps=[], series=[]), [])
    with pytest.raises(ValueError):  # NaN
        assess_risk(
            ImpactEnsemble(units="MW", timestamps=_ts(2), series=[[1.0, float("nan")], [2.0, 3.0]]),
            [],
        )
    with pytest.raises(ValueError):  # ragged
        assess_risk(ImpactEnsemble(units="MW", timestamps=_ts(2), series=[[1.0, 2.0], [3.0]]), [])
    with pytest.raises(ValueError):  # hour count != timestamps
        assess_risk(ImpactEnsemble(units="MW", timestamps=_ts(3), series=[[1.0, 2.0], [3.0, 4.0]]), [])


def test_fan_is_monotonic_p10_le_p50_le_p90() -> None:
    series = [[float((v * 7 + h * 3) % 50) for h in range(8)] for v in range(20)]
    r = assess_risk(ImpactEnsemble(units="MW", timestamps=_ts(8), series=series), [])
    for a, b, c in zip(r.p10, r.p50, r.p90):
        assert a <= b <= c
