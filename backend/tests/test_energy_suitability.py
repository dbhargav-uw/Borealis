"""EnergySuitabilityModel tests — solar PVWatts-style yield + wind power density."""

from __future__ import annotations

import pytest

from resources.types import ResourceCell
from verticals.energy.suitability import EnergySuitabilityModel

MODEL = EnergySuitabilityModel()


def _cell(ghi: float, temp: float, wind: float) -> ResourceCell:
    return ResourceCell(
        lat=37.0, lon=-5.0,
        values={"ALLSKY_SFC_SW_DWN": ghi, "T2M": temp, "WS50M": wind},
    )


def test_solar_specific_yield_sane() -> None:
    s = MODEL.score_cell(_cell(5.5, 18.0, 6.0), {"lens": "solar"})
    assert MODEL.metric_units({"lens": "solar"}) == "kWh/kWp/yr"
    assert 1300 <= s.raw <= 2000                         # good site specific yield
    assert 0.14 <= s.metrics["capacity_factor"] <= 0.24


def test_wind_power_density_sane() -> None:
    s = MODEL.score_cell(_cell(4.0, 14.0, 9.0), {"lens": "wind"})
    assert MODEL.metric_units({"lens": "wind"}) == "W/m²"
    assert s.raw == pytest.approx(0.5 * 1.225 * 9.0**3, rel=1e-6)   # 446.5 W/m²
    assert s.metrics["mean_wind_50m_ms"] == 9.0


def test_lens_orderings() -> None:
    assert MODEL.score_cell(_cell(6.0, 20, 4.0), {"lens": "solar"}).raw > \
        MODEL.score_cell(_cell(3.0, 20, 4.0), {"lens": "solar"}).raw   # sunnier wins solar
    assert MODEL.score_cell(_cell(4.0, 15, 10.0), {"lens": "wind"}).raw > \
        MODEL.score_cell(_cell(4.0, 15, 5.0), {"lens": "wind"}).raw    # windier wins wind


def test_temperature_derate() -> None:
    # Same GHI, colder cell -> higher performance ratio -> higher yield.
    assert MODEL.score_cell(_cell(5.0, 5.0, 6.0), {"lens": "solar"}).raw > \
        MODEL.score_cell(_cell(5.0, 40.0, 6.0), {"lens": "solar"}).raw


def test_unknown_lens_raises() -> None:
    with pytest.raises(ValueError, match="lens"):
        MODEL.score_cell(_cell(5, 20, 6), {"lens": "tidal"})
