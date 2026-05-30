"""Wind power-curve unit tests (pure numpy, no network)."""

from __future__ import annotations

import numpy as np
import pytest

from verticals.energy.wind import (
    extrapolate_to_hub,
    turbine_power_fraction,
    wind_power_mw,
)

CURVE = dict(cut_in_ms=3.0, rated_ms=12.0, cut_out_ms=25.0)
FARM = dict(rated_power_kw=3000.0, n_turbines=10, **CURVE)  # 30 MW farm


def test_below_cut_in_is_zero() -> None:
    w = np.array([[0.0, 1.0, 2.9, 3.0]])  # last is exactly cut_in -> frac 0
    mw = wind_power_mw(w, **FARM)
    assert np.allclose(mw[0, :3], 0.0)
    assert mw[0, 3] == pytest.approx(0.0, abs=1e-9)


def test_at_and_above_rated_is_farm_rated() -> None:
    w = np.array([[12.0, 15.0, 20.0, 25.0]])  # rated..cut_out all clamp to full output
    mw = wind_power_mw(w, **FARM)
    assert np.allclose(mw, 30.0)


def test_above_cut_out_is_zero() -> None:
    w = np.array([[25.01, 30.0, 40.0]])
    mw = wind_power_mw(w, **FARM)
    assert np.allclose(mw, 0.0)


def test_midrange_is_sensible_fraction() -> None:
    # v=7.5: frac = (7.5^3 - 3^3)/(12^3 - 3^3) = 394.875/1701 = 0.23214...
    frac = turbine_power_fraction(np.array([7.5]), **CURVE)[0]
    assert frac == pytest.approx(0.232142857, rel=1e-6)
    mw = wind_power_mw(np.array([[7.5]]), **FARM)[0, 0]
    assert mw == pytest.approx(0.232142857 * 30.0, rel=1e-6)  # ~6.964 MW
    assert 0.0 < mw < 30.0


def test_monotonic_nondecreasing_up_to_cut_out() -> None:
    v = np.linspace(0.0, 25.0, 100)
    frac = turbine_power_fraction(v, **CURVE)
    assert np.all(np.diff(frac) >= -1e-12)
    assert frac.min() >= 0.0 and frac.max() <= 1.0


def test_shape_preserved_member_hour() -> None:
    w = np.full((5, 24), 8.0)  # 5 members, 24 hours
    mw = wind_power_mw(w, **FARM)
    assert mw.shape == (5, 24)
    assert np.all(mw > 0) and np.all(mw < 30.0)


def test_cut_out_cliff_creates_ensemble_spread() -> None:
    # Members straddling cut_out swing rated<->0 — real signal, must show as spread.
    w = np.array([[24.9], [25.1]])
    mw = wind_power_mw(w, **FARM)
    assert mw[0, 0] == pytest.approx(30.0)
    assert mw[1, 0] == pytest.approx(0.0)


def test_extrapolation_matches_powerlaw() -> None:
    v10 = np.array([[6.0]])
    vhub = extrapolate_to_hub(v10, ref_height_m=10.0, hub_height_m=100.0, alpha=0.143)
    assert vhub[0, 0] == pytest.approx(6.0 * (10.0**0.143), rel=1e-6)  # ~8.33 m/s
    assert vhub[0, 0] > v10[0, 0]


def test_invalid_curve_raises() -> None:
    with pytest.raises(ValueError):
        turbine_power_fraction(np.array([5.0]), cut_in_ms=12.0, rated_ms=3.0, cut_out_ms=25.0)
