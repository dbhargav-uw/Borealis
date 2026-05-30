"""AgriSuitabilityModel + agriculture route tests (the 2nd vertical, provider mocked)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.suitability as suit_module
from api.main import app
from resources.types import ResourceCell, ResourceGrid
from verticals.agri.suitability import AgriSuitabilityModel

MODEL = AgriSuitabilityModel()
client = TestClient(app)


def _cell(temp: float, precip_mm_day: float) -> ResourceCell:
    return ResourceCell(lat=10.0, lon=10.0, values={"T2M": temp, "PRECTOTCORR": precip_mm_day})


def test_units_and_metrics() -> None:
    assert MODEL.metric_units({}) == "GDD·yr (water-adjusted)"
    s = MODEL.score_cell(_cell(20.0, 2.0), {})
    assert set(s.metrics) >= {"mean_temp_c", "annual_precip_mm", "growing_degree_days", "water_factor"}
    assert s.metrics["growing_degree_days"] == pytest.approx((20.0 - 10.0) * 365.0)


def test_warm_wet_beats_cold_dry() -> None:
    warm_wet = MODEL.score_cell(_cell(22.0, 3.0), {}).raw   # temperate, ~1095 mm/yr
    cold_dry = MODEL.score_cell(_cell(2.0, 0.2), {}).raw    # cold, ~73 mm/yr
    assert warm_wet > cold_dry


def test_hot_desert_water_limited() -> None:
    s = MODEL.score_cell(_cell(30.0, 0.1), {})  # warm but ~36 mm/yr
    assert s.metrics["water_factor"] < 0.1


class _AgriProvider:
    async def get_resource_grid(self, bbox: tuple, resolution: float, variables: list[str]) -> ResourceGrid:
        cells = [
            ResourceCell(lat=10.0, lon=10.0, values={"T2M": 22.0, "PRECTOTCORR": 3.0}),
            ResourceCell(lat=20.0, lon=20.0, values={"T2M": 2.0, "PRECTOTCORR": 0.2}),
        ]
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=cells)


def test_agriculture_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(suit_module, "get_resource_provider", lambda base_url=None: _AgriProvider())
    body = {
        "vertical": "agriculture",
        "region": {"lat_min": 5, "lon_min": 5, "lat_max": 25, "lon_max": 25},
        "params": {},
        "top_n": 2,
        "land_only": False,
    }
    resp = client.post("/api/suitability", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["metric_units"] == "GDD·yr (water-adjusted)"
    assert data["ranked_sites"][0]["lat"] == 10.0  # warm/wet cell beats cold/dry


def test_both_verticals_registered() -> None:
    import registry

    assert {"energy", "agriculture"} <= set(registry.registered_suitability_verticals())
