"""End-to-end EnergyModel.apply tests (solar + wind + fallback + edge cases) on a
synthetic forecast, no network. CLAUDE.md names energy the most error-prone path."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from operational.energy import EnergyModel
from operational.forecast.types import EnsembleForecast
from verticals.base import Asset

MODEL = EnergyModel()


def _forecast(members: int, hours: int, *, with_100m: bool = True) -> EnsembleForecast:
    ts = [datetime(2026, 6, 21, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(hours)]
    ghi = [[max(0.0, 600 - abs((i % 24) - 19) * 80) for i in range(hours)] for _ in range(members)]
    variables: dict[str, list[list[float]]] = {
        "shortwave_radiation": ghi,
        "temperature_2m": [[20.0] * hours for _ in range(members)],
        "wind_speed_10m": [[6.0] * hours for _ in range(members)],
    }
    if with_100m:
        variables["wind_speed_100m"] = [[8.0 + m] * hours for m in range(members)]
    return EnsembleForecast(lat=33.45, lon=-112.07, timestamps=ts, members=members, variables=variables)


def test_solar_apply_shape_units_nonneg() -> None:
    asset = Asset(name="s", lat=33.45, lon=-112.07, vertical="energy",
                  params={"kind": "solar", "dc_capacity_kw": 1000})
    imp = MODEL.apply(_forecast(4, 24), asset)
    assert imp.units == "MW"
    assert len(imp.series) == 4 and all(len(r) == 24 for r in imp.series)
    arr = np.asarray(imp.series)
    assert (arr >= 0).all() and arr.max() > 0  # some daytime generation


def test_wind_apply_uses_native_100m() -> None:
    asset = Asset(name="w", lat=54, lon=3, vertical="energy",
                  params={"kind": "wind", "rated_power_kw": 3000, "n_turbines": 10})
    imp = MODEL.apply(_forecast(3, 12), asset)  # 30 MW farm, winds 8..10 m/s
    arr = np.asarray(imp.series)
    assert imp.units == "MW" and arr.shape == (3, 12)
    assert (arr > 0).all() and (arr < 30).all()  # partial load


def test_wind_fallback_extrapolates_from_10m() -> None:
    fc = _forecast(2, 6, with_100m=False)  # only wind_speed_10m present
    asset = Asset(name="w", lat=54, lon=3, vertical="energy",
                  params={"kind": "wind", "rated_power_kw": 3000, "n_turbines": 5})
    arr = np.asarray(MODEL.apply(fc, asset).series)  # 6 m/s @10m -> ~8.33 m/s @100m
    assert arr.shape == (2, 6) and (arr > 0).all()


def test_solar_member_count_mismatch_raises() -> None:
    fc = _forecast(3, 6)
    fc.variables["temperature_2m"] = fc.variables["temperature_2m"][:2]  # drop a member
    asset = Asset(name="s", lat=33.45, lon=-112.07, vertical="energy",
                  params={"kind": "solar", "dc_capacity_kw": 1000})
    with pytest.raises(ValueError, match="mismatched"):
        MODEL.apply(fc, asset)


def test_unknown_kind_raises() -> None:
    asset = Asset(name="x", lat=0, lon=0, vertical="energy", params={"kind": "tidal"})
    with pytest.raises(ValueError, match="kind"):
        MODEL.apply(_forecast(2, 3), asset)


def test_nan_input_propagates_not_laundered() -> None:
    # A genuine forecast gap must survive to the risk NaN-guard, not become 0 MW.
    fc = _forecast(2, 6)
    fc.variables["wind_speed_100m"][0][3] = float("nan")
    asset = Asset(name="w", lat=54, lon=3, vertical="energy",
                  params={"kind": "wind", "rated_power_kw": 3000, "n_turbines": 10})
    imp = MODEL.apply(fc, asset)
    assert math.isnan(imp.series[0][3])
