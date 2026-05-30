"""POST /api/assess tests via TestClient, with the forecast provider mocked (offline)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api.assess as assess_module
from api.main import app
from forecast.types import EnsembleForecast

client = TestClient(app)


class _FakeProvider:
    """Deterministic ensemble: constant daytime-ish GHI, temp, and wind, 3 members."""

    def __init__(self, members: int = 3) -> None:
        self.members = members

    async def get_ensemble_forecast(
        self, lat: float, lon: float, hours: int, variables: list[str]
    ) -> EnsembleForecast:
        ts = [datetime(2026, 5, 30, tzinfo=timezone.utc) + timedelta(hours=i) for i in range(hours)]
        defaults = {"shortwave_radiation": 400.0, "temperature_2m": 20.0}
        out = {
            v: [[defaults.get(v, 8.0)] * hours for _ in range(self.members)] for v in variables
        }
        return EnsembleForecast(lat=lat, lon=lon, timestamps=ts, members=self.members, variables=out)


SOLAR_ASSET = {
    "name": "West Texas Solar",
    "lat": 31.9,
    "lon": -102.1,
    "vertical": "energy",
    "params": {
        "kind": "solar",
        "dc_capacity_kw": 100000,
        "surface_tilt": 25,
        "surface_azimuth": 180,
        "gamma_pdc": -0.004,
        "system_loss": 0.14,
        "ac_dc_ratio": 1.2,
    },
}


@pytest.fixture
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assess_module, "get_provider", lambda base_url=None: _FakeProvider())


def test_assess_energy_solar_ok(mock_provider: None) -> None:
    body = {
        "vertical": "energy",
        "asset": SOLAR_ASSET,
        "thresholds": [{"name": "below_bid_floor", "direction": "below", "value": 40.0}],
        "hours": 24,
    }
    resp = client.post("/api/assess", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) == {"forecast_summary", "impact_fan", "risk", "briefing"}
    assert data["briefing"] is None
    assert data["forecast_summary"]["members"] == 3
    assert data["impact_fan"]["units"] == "MW"
    assert len(data["impact_fan"]["p50"]) == 24
    assert len(data["risk"]["p10"]) == 24
    tp = data["risk"]["thresholds"][0]
    assert tp["name"] == "below_bid_floor"
    assert 0.0 <= tp["prob_any"] <= 1.0


def test_assess_unknown_vertical_404(mock_provider: None) -> None:
    body = {
        "vertical": "nope",
        "asset": {"name": "x", "lat": 0, "lon": 0, "vertical": "nope"},
        "thresholds": [],
    }
    resp = client.post("/api/assess", json=body)
    assert resp.status_code == 404
    data = resp.json()
    assert data["code"] == "unknown_vertical"
    assert "energy" in data["registered"]


def test_assess_malformed_body_422(mock_provider: None) -> None:
    body = {"vertical": "energy", "asset": SOLAR_ASSET, "hours": 500}  # hours > 168
    resp = client.post("/api/assess", json=body)
    assert resp.status_code == 422


def test_assess_bad_params_422(mock_provider: None) -> None:
    bad = {**SOLAR_ASSET, "params": {"kind": "solar"}}  # missing dc_capacity_kw
    resp = client.post("/api/assess", json={"vertical": "energy", "asset": bad, "hours": 24})
    assert resp.status_code == 422
    assert resp.json()["code"] in {"invalid_impact", "validation_error"}


def test_assess_provider_error_502(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        async def get_ensemble_forecast(self, *a: object, **k: object) -> EnsembleForecast:
            raise RuntimeError("upstream down")

    monkeypatch.setattr(assess_module, "get_provider", lambda base_url=None: _Boom())
    resp = client.post("/api/assess", json={"vertical": "energy", "asset": SOLAR_ASSET, "hours": 24})
    assert resp.status_code == 502
    assert resp.json()["code"] == "forecast_provider_error"


WIND_ASSET = {
    "name": "North Sea Wind",
    "lat": 54.0,
    "lon": 3.0,
    "vertical": "energy",
    "params": {"kind": "wind", "rated_power_kw": 3000, "n_turbines": 10},
}


def test_assess_energy_wind_ok(mock_provider: None) -> None:
    body = {
        "vertical": "energy",
        "asset": WIND_ASSET,
        "thresholds": [{"name": "below_10MW", "direction": "below", "value": 10.0}],
        "hours": 24,
    }
    resp = client.post("/api/assess", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["impact_fan"]["units"] == "MW"
    assert len(data["impact_fan"]["p50"]) == 24
    assert data["risk"]["thresholds"][0]["name"] == "below_10MW"
