"""POST /api/best-site tests — region scoring + hazard penalties + pick, fully offline.

The endpoint composes existing engines, so we mock the externals (LLM parse, resource grid, elevation,
tornado, LLM explanation) and assert the wiring: suitability ranking + hazard penalties pick the right
cell, candidates are sorted, masks/units flow, and the result degrades gracefully without a key.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.best_site as bs
from api.main import app
from api.tornado import TornadoClimatology
from briefing import BestSiteQuery, BriefingUnavailable
from resources.types import ResourceCell, ResourceGrid

client = TestClient(app)

# Two land cells in Texas: A = sunny, high, dry inland; B = less sunny, low-lying Gulf coast.
CELL_A = (31.5, -99.0)  # inland West Texas
CELL_B = (29.7, -95.3)  # Houston (coastal, low elevation)


class _FakeProvider:
    async def get_resource_grid(self, bbox: tuple, resolution: float, variables: list[str]) -> ResourceGrid:
        cells = [
            ResourceCell(lat=CELL_A[0], lon=CELL_A[1], values={"ALLSKY_SFC_SW_DWN": 6.2, "T2M": 20, "WS50M": 7.0, "PRECTOTCORR": 1.5}),
            ResourceCell(lat=CELL_B[0], lon=CELL_B[1], values={"ALLSKY_SFC_SW_DWN": 5.0, "T2M": 23, "WS50M": 6.0, "PRECTOTCORR": 3.5}),
        ]
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=cells)


def _clim(freq: float) -> TornadoClimatology:
    return TornadoClimatology(
        region="Texas", annual_frequency=freq, ef_distribution={"EF0": 1.0}, dominant_ef=0, negligible=False, source="SPC",
    )


@pytest.fixture(autouse=True)
def _mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    bs._cache.clear()
    monkeypatch.setattr(bs, "select_resource_provider", lambda *a, **k: _FakeProvider())

    async def _parse(**_k: object) -> BestSiteQuery:
        return BestSiteQuery(
            label="Solar farm, Texas", region_label="Texas, USA", building_type="solar farm",
            lat_min=28.0, lon_min=-103.0, lat_max=34.0, lon_max=-94.0, objective="solar",
            avoid_flood=False, avoid_tornado=False,
        )
    monkeypatch.setattr(bs, "parse_best_site_query", _parse)

    async def _elev(points: list[tuple[float, float]], **_k: object) -> list[float | None]:
        # align to provider cell order: A inland high, B coastal low
        return [500.0 if abs(la - CELL_A[0]) < 0.1 else 2.0 for la, _ in points]
    monkeypatch.setattr(bs, "fetch_elevations", _elev)

    async def _torn(lat: float, lon: float) -> TornadoClimatology:
        return _clim(0.5)
    monkeypatch.setattr(bs, "tornado_climatology", _torn)

    async def _no_llm(**_k: object) -> object:
        raise BriefingUnavailable("no key in tests")
    monkeypatch.setattr(bs, "generate_best_site_explanation", _no_llm)


def test_best_site_picks_higher_suitability_lower_hazard() -> None:
    r = client.post("/api/best-site", json={"query": "find the best place in Texas for a solar farm"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["objective"] == "solar" and d["metric_units"] == "kWh/kWp/yr"
    # inland sunny + high-elevation cell wins over the low-lying coastal one
    assert d["best_site"]["lat"] == pytest.approx(CELL_A[0])
    assert d["best_site"]["score"] >= d["top_candidates"][-1]["score"]  # sorted desc
    m = d["best_site"]["metrics"]
    assert "suitability_score" in m and "flood_penalty" in m and "final_score" in m
    assert m["elevation_m"] == pytest.approx(500.0)
    assert "not a bankable" in d["disclaimer"].lower()


def test_best_site_explanation_degrades_without_key() -> None:
    d = client.post("/api/best-site", json={"query": "best solar site in Texas"}).json()
    assert d["explanation"] is None  # no key in tests → additive explanation omitted


def test_best_site_ocean_region_has_no_site(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Empty:
        async def get_resource_grid(self, *a: object, **k: object) -> ResourceGrid:
            return ResourceGrid(bbox=(0, 0, 2, 2), resolution=1.0, variables=[], cells=[])
    monkeypatch.setattr(bs, "select_resource_provider", lambda *a, **k: _Empty())
    d = client.post("/api/best-site", json={"query": "best solar site in the open ocean"}).json()
    assert d["best_site"] is None and d["top_candidates"] == [] and d["message"]


def test_helpers() -> None:
    assert bs._flood_penalty(1.0) == 1.0 and bs._flood_penalty(500.0) == 0.03 and bs._flood_penalty(None) == 0.0
    assert bs._tornado_penalty(1.5) == 1.0 and bs._tornado_penalty(0.0) == 0.0
    assert bs._clamp_axis(28.0, 50.0, 90.0) == (34.0, 44.0)  # 22° span clamped to 10°
