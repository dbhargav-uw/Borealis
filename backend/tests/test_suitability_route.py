"""POST /api/suitability tests via TestClient, with the resource provider mocked (offline)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.suitability as suit_module
from api.main import app
from resources.types import ResourceCell, ResourceGrid

client = TestClient(app)

REGION = {"lat_min": 36, "lon_min": -10, "lat_max": 44, "lon_max": 0}


class _FakeProvider:
    """Sunny south (good solar) vs windy north (good wind) — so the lenses rank oppositely."""

    async def get_resource_grid(
        self, bbox: tuple, resolution: float, variables: list[str]
    ) -> ResourceGrid:
        cells = [
            ResourceCell(lat=37.0, lon=-5.0, values={"ALLSKY_SFC_SW_DWN": 6.0, "T2M": 19, "WS50M": 5.0}),
            ResourceCell(lat=43.0, lon=-5.0, values={"ALLSKY_SFC_SW_DWN": 3.5, "T2M": 13, "WS50M": 9.0}),
        ]
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=cells)


@pytest.fixture
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(suit_module, "select_resource_provider", lambda *a, **k: _FakeProvider())


def test_suitability_solar_ok(mock_provider: None) -> None:
    body = {"vertical": "energy", "region": REGION, "resolution": 0.5,
            "params": {"lens": "solar"}, "top_n": 2}
    resp = client.post("/api/suitability", json=body)
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["metric_units"] == "kWh/kWp/yr"
    assert d["n_cells"] == 2
    assert {c["score"] for c in d["cells"]} == {0.0, 1.0}      # min-max of two cells
    assert d["ranked_sites"][0]["rank"] == 1
    assert d["ranked_sites"][0]["lat"] == 37.0                  # sunnier south wins solar
    assert d["briefing"] is None
    assert any("RELATIVE" in c for c in d["ranked_sites"][0]["caveats"])


def test_suitability_wind_ranks_differently(mock_provider: None) -> None:
    body = {"vertical": "energy", "region": REGION, "params": {"lens": "wind"}, "top_n": 2}
    d = client.post("/api/suitability", json=body).json()
    assert d["metric_units"] == "W/m²"
    assert d["ranked_sites"][0]["lat"] == 43.0                  # windier north wins wind


def test_unknown_vertical_404(mock_provider: None) -> None:
    resp = client.post("/api/suitability",
                       json={"vertical": "nope", "region": REGION, "params": {"lens": "solar"}})
    assert resp.status_code == 404
    assert resp.json()["code"] == "unknown_vertical"


def test_bad_bbox_422() -> None:
    bad = {"vertical": "energy",
           "region": {"lat_min": 44, "lon_min": -10, "lat_max": 36, "lon_max": 0},
           "params": {"lens": "solar"}}
    assert client.post("/api/suitability", json=bad).status_code == 422


def test_provider_error_502(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        async def get_resource_grid(self, *a: object, **k: object) -> ResourceGrid:
            raise RuntimeError("POWER down")

    monkeypatch.setattr(suit_module, "select_resource_provider", lambda *a, **k: _Boom())
    resp = client.post("/api/suitability",
                       json={"vertical": "energy", "region": REGION, "params": {"lens": "solar"}})
    assert resp.status_code == 502
    assert resp.json()["code"] == "resource_provider_error"


def test_fine_resolution_small_region_ok(mock_provider: None) -> None:
    """A 0.1° request over a tight box (east of San Jose) is now accepted (floor was 0.5°)."""
    body = {
        "vertical": "energy",
        "region": {"lat_min": 37.2, "lon_min": -121.8, "lat_max": 37.6, "lon_max": -121.4},
        "resolution": 0.1,
        "params": {"lens": "solar"},
        "source": "auto",
        "top_n": 2,
    }
    resp = client.post("/api/suitability", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["n_cells"] == 2


def test_resolution_below_floor_422() -> None:
    """0.05° is below the new 0.1° floor -> validation error."""
    body = {"vertical": "energy", "region": REGION, "resolution": 0.05, "params": {"lens": "solar"}}
    assert client.post("/api/suitability", json=body).status_code == 422
