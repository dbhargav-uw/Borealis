"""GET/POST /api/analysis tests — the aggregation dossier, fully offline.

The endpoint COMPOSES existing engines, so we mock the three external inputs (resource grid, live
storm/alert feeds, the Anthropic synthesis) and assert the wiring + the honesty framing: relative
resource read, elevation-based flood read, reused SPC tornado climatology, live proximity/containment,
and graceful degradation of the LLM insurance/summary.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api.alerts as alerts_mod
import api.analysis as analysis_mod
import api.storms as storms_mod
from api.main import app
from briefing import BriefingUnavailable
from resources.types import ResourceCell, ResourceGrid
from storms.types import ActiveStorm, AlertsResponse, StormsResponse, WeatherAlert

client = TestClient(app)

# Oklahoma (Tornado Alley) so the reused SPC climatology is non-negligible.
LAT, LON = 35.0, -97.5


class _FakeProvider:
    async def get_resource_grid(self, bbox: tuple, resolution: float, variables: list[str]) -> ResourceGrid:
        cells = [
            ResourceCell(lat=35.0, lon=-97.5, values={"ALLSKY_SFC_SW_DWN": 5.5, "T2M": 16, "WS50M": 7.5, "PRECTOTCORR": 2.4}),
            ResourceCell(lat=36.0, lon=-97.5, values={"ALLSKY_SFC_SW_DWN": 4.0, "T2M": 14, "WS50M": 5.0, "PRECTOTCORR": 2.0}),
        ]
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=cells)


class _EmptyProvider:
    async def get_resource_grid(self, bbox: tuple, resolution: float, variables: list[str]) -> ResourceGrid:
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=[])


_NOW = datetime(2026, 5, 31, tzinfo=timezone.utc).isoformat()

# An NWS tornado-warning polygon covering (LON, LAT).
_ALERT = WeatherAlert(
    id="x", event="Tornado Warning", severity="Extreme", certainty="Observed", urgency="Immediate",
    headline="TOR", area_desc="Cleveland, OK",
    geometry={"type": "Polygon", "coordinates": [[[-98.0, 34.5], [-97.0, 34.5], [-97.0, 35.5], [-98.0, 35.5], [-98.0, 34.5]]]},
    source="NWS",
)
_STORM_FAR = ActiveStorm(
    id="al012026", name="Faraway", basin="AL", classification="HU", category=3,
    lat=20.0, lon=-60.0, max_wind_kt=100, advisory_time=_NOW, source="NHC",
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis_mod._cache.clear()  # no cross-test cache bleed
    monkeypatch.setattr(analysis_mod, "select_resource_provider", lambda *a, **k: _FakeProvider())
    # Default: no live storms/alerts and no LLM (offline). Individual tests override.
    async def _no_storms() -> StormsResponse:
        return StormsResponse(storms=[], as_of=_NOW, source="NHC", coverage="cov")
    async def _no_alerts() -> AlertsResponse:
        return AlertsResponse(alerts=[], as_of=_NOW, source="NWS", coverage="cov")
    monkeypatch.setattr(storms_mod, "storms", _no_storms)
    monkeypatch.setattr(alerts_mod, "alerts", _no_alerts)
    async def _no_llm(**_k: object) -> object:
        raise BriefingUnavailable("no key in tests")
    monkeypatch.setattr(analysis_mod, "generate_analysis_briefing", _no_llm)


def _post(**over: object) -> dict:
    body = {"lat": LAT, "lon": LON, "building_type": "hospital", "intent": "general", "elevation_m": 3.0}
    body.update(over)
    resp = client.post("/api/analysis", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- structure + resource (relative comparator) --------------------------------------
def test_dossier_shape_and_resource() -> None:
    d = _post()
    assert set(d) >= {"location", "resource", "hazards", "insurance", "summary", "disclaimer"}
    loc = d["location"]
    assert loc["lat"] == LAT and loc["building_type"] == "hospital" and loc["elevation_m"] == 3.0
    res = d["resource"]
    assert res["available"] is True
    assert res["solar"]["units"] == "kWh/kWp/yr" and res["wind"]["units"] == "W/m²"
    assert 0.0 <= res["solar"]["score"] <= 1.0
    # sunnier/windier south cell (35.0) is nearest the point and tops both lenses (2-cell min-max → 1.0)
    assert res["solar"]["score"] == 1.0 and res["wind"]["score"] == 1.0
    assert "solar" in res["solar"]["read"].lower()
    assert "not bankable" in res["note"].lower()
    assert "not" in d["disclaimer"].lower() and "advice" in d["disclaimer"].lower()


def test_crop_lens_only_for_agri_building() -> None:
    assert _post(building_type="hospital")["resource"]["crop"] is None
    crop = _post(building_type="farm")["resource"]["crop"]
    assert crop is not None and crop["units"].startswith("GDD")


def test_ocean_resource_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_mod, "select_resource_provider", lambda *a, **k: _EmptyProvider())
    res = _post(lat=0.0, lon=-150.0)["resource"]  # open Pacific
    assert res["available"] is False and res["solar"] is None and res["message"]


# --- hazards (reused real data, labeled) ---------------------------------------------
def test_flood_exposure_elevation_bands() -> None:
    assert _post(elevation_m=1.0)["hazards"]["flood"]["low_lying"] is True
    high = _post(elevation_m=400.0)["hazards"]["flood"]
    assert high["low_lying"] is False and "illustrative" in high["scenario_note"].lower()
    unknown = _post(elevation_m=None)["hazards"]["flood"]
    assert unknown["elevation_m"] is None and "not assessed" in unknown["exposure"].lower()


def test_tornado_reuses_spc_climatology() -> None:
    torn = _post()["hazards"]["tornado"]
    assert torn["negligible"] is False  # Oklahoma is Tornado Alley
    assert "SPC" in torn["source"] and "EF" in torn["read"]


def test_live_context_alert_containment(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _with_alert() -> AlertsResponse:
        return AlertsResponse(alerts=[_ALERT], as_of=_NOW, source="NWS", coverage="cov")
    monkeypatch.setattr(alerts_mod, "alerts", _with_alert)
    live = _post()["hazards"]["live"]
    assert live["available"] is True and live["under_alert"] is True
    assert live["alert_event"] == "Tornado Warning" and live["as_of"]


def test_live_context_far_storm_not_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _far() -> StormsResponse:
        return StormsResponse(storms=[_STORM_FAR], as_of=_NOW, source="NHC", coverage="cov")
    monkeypatch.setattr(storms_mod, "storms", _far)
    live = _post()["hazards"]["live"]
    assert live["nearby_storm"] is None and live["under_alert"] is False


# --- LLM synthesis degrades gracefully (no key) --------------------------------------
def test_insurance_and_summary_degrade_without_llm() -> None:
    d = _post()
    assert d["insurance"] == [] and d["summary"] is None


# --- pure helpers --------------------------------------------------------------------
def test_point_in_geometry() -> None:
    poly = {"type": "Polygon", "coordinates": [[[-98.0, 34.5], [-97.0, 34.5], [-97.0, 35.5], [-98.0, 35.5], [-98.0, 34.5]]]}
    assert analysis_mod._point_in_geometry(-97.5, 35.0, poly) is True
    assert analysis_mod._point_in_geometry(-90.0, 35.0, poly) is False
    assert analysis_mod._point_in_geometry(-97.5, 35.0, None) is False


def test_haversine_km() -> None:
    assert analysis_mod._haversine_km(0, 0, 0, 0) == pytest.approx(0.0)
    assert analysis_mod._haversine_km(0, 0, 0, 1) == pytest.approx(111.3, abs=1.0)


def test_cache_hit_serves_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    class _Counting:
        async def get_resource_grid(self, *a: object, **k: object) -> ResourceGrid:
            calls["n"] += 1
            return await _FakeProvider().get_resource_grid(*a, **k)
    monkeypatch.setattr(analysis_mod, "select_resource_provider", lambda *a, **k: _Counting())
    _post(lat=10.0, lon=10.0)
    _post(lat=10.0, lon=10.0)
    assert calls["n"] == 1  # second call served from the per-location cache
