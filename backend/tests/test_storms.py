"""LIVE storm-feed tests — pure parsers + the /api/storms, /api/alerts routes (offline, mocked).

Both feeds are off-season-empty in the wild, so we test against saved fixture shapes (a populated NHC
storm + a tornado-warning GeoJSON feature) plus the empty case (which must be normal, not an error).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import api.alerts as alerts_mod
import api.storms as storms_mod
from api.main import app
from operational.forecast.current_wind import wind_uv
from storms.cache import TTLCache
from storms.nhc import build_storms_response, parse_active_storms, parse_storm, saffir_simpson_category
from storms.nws import parse_alert
from storms.types import AlertsResponse, StormsResponse

client = TestClient(app)

# A populated NHC `activeStorms[]` entry (off-season the live list is empty; this is the real shape).
SAMPLE_STORM = {
    "id": "al062023",
    "binNumber": "AT2",
    "name": "Margot",
    "classification": "HU",
    "intensity": "75",      # knots → Cat 1
    "pressure": "975",
    "latitude": "31.2N",
    "longitude": "44.5W",
    "latitudeNumeric": 31.2,
    "longitudeNumeric": -44.5,
    "movementDir": 315,     # NW
    "movementSpeed": 12,
    "lastUpdate": "2023-09-15T15:00:00.000Z",
}

# A tornado-warning GeoJSON Feature (storm-based polygon).
SAMPLE_ALERT = {
    "id": "urn:oid:2.49.0.1.840.0.test",
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[-97.1, 35.2], [-97.0, 35.2], [-97.0, 35.3], [-97.1, 35.3], [-97.1, 35.2]]],
    },
    "properties": {
        "event": "Tornado Warning",
        "severity": "Extreme",
        "certainty": "Observed",
        "urgency": "Immediate",
        "headline": "Tornado Warning issued May 31 at 8:00PM CDT",
        "areaDesc": "Cleveland, OK; McClain, OK",
        "onset": "2026-05-31T20:00:00-05:00",
        "expires": "2026-05-31T20:30:00-05:00",
    },
}


# --- Saffir–Simpson ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kt,cat",
    [(30, 0), (50, 0), (64, 1), (82, 1), (83, 2), (96, 3), (113, 4), (137, 5), (180, 5)],
)
def test_saffir_simpson_category(kt: float, cat: int) -> None:
    assert saffir_simpson_category(kt) == cat


# --- NHC parsing ------------------------------------------------------------------------------
def test_parse_storm_maps_scalars() -> None:
    s = parse_storm(SAMPLE_STORM)
    assert s.id == "al062023" and s.name == "Margot" and s.basin == "AL"
    assert s.classification == "HU" and s.category == 1
    assert s.lat == pytest.approx(31.2) and s.lon == pytest.approx(-44.5)
    assert s.max_wind_kt == pytest.approx(75.0) and s.min_pressure_mb == pytest.approx(975.0)
    assert s.movement == "NW at 12 mph"
    assert s.source.startswith("NOAA NHC")


def test_parse_active_storms_skips_malformed_and_empty() -> None:
    assert parse_active_storms({"activeStorms": []}) == []
    assert parse_active_storms({}) == []
    mixed = {"activeStorms": [SAMPLE_STORM, {"id": "bad"}]}  # 2nd lacks position → skipped
    out = parse_active_storms(mixed)
    assert len(out) == 1 and out[0].id == "al062023"


def test_parse_active_storms_filters_to_named_cyclones() -> None:
    # A tropical depression (TD, 25 kt), a potential TC (PTC), and an invest are NOT rendered;
    # the named hurricane (HU, 75 kt) is. Only genuine named TS+ systems survive.
    td = {**SAMPLE_STORM, "id": "al072023", "name": "Seven", "classification": "TD", "intensity": "25"}
    ptc = {**SAMPLE_STORM, "id": "al082023", "name": "Eight", "classification": "PTC", "intensity": "40"}
    invest = {**SAMPLE_STORM, "id": "al902023", "name": "Invest", "classification": "DB", "intensity": "30"}
    out = parse_active_storms({"activeStorms": [SAMPLE_STORM, td, ptc, invest]})
    assert [s.id for s in out] == ["al062023"]  # only Margot (HU, 75 kt) is kept


def test_build_storms_response_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storms_nhc_httpx(), "AsyncClient", _fake_client({"activeStorms": [SAMPLE_STORM]}))
    resp = asyncio.run(build_storms_response("http://x"))
    assert isinstance(resp, StormsResponse)
    assert len(resp.storms) == 1 and resp.storms[0].category == 1
    assert resp.as_of and resp.coverage and "Atlantic" in resp.coverage


# --- NWS parsing ------------------------------------------------------------------------------
def test_parse_alert_keeps_geometry_and_fields() -> None:
    a = parse_alert(SAMPLE_ALERT)
    assert a.event == "Tornado Warning" and a.severity == "Extreme"
    assert a.area_desc.startswith("Cleveland")
    assert a.issued_at == "2026-05-31T20:00:00-05:00"
    assert a.expires_at == "2026-05-31T20:30:00-05:00"
    assert a.geometry is not None and a.geometry["type"] == "Polygon"
    assert a.source.startswith("NWS")


def test_parse_alert_handles_null_geometry() -> None:
    feat = {"id": "x", "geometry": None, "properties": {"event": "Tornado Watch", "areaDesc": "zone"}}
    a = parse_alert(feat)
    assert a.geometry is None and a.event == "Tornado Watch"


# --- wind u/v derivation ----------------------------------------------------------------------
def test_wind_uv_signs() -> None:
    # FROM north (0°) → blows toward south: v<0, u≈0
    u, v = wind_uv(10.0, 0.0)
    assert u == pytest.approx(0.0, abs=1e-9) and v == pytest.approx(-10.0)
    # FROM east (90°) → toward west: u<0, v≈0
    u, v = wind_uv(10.0, 90.0)
    assert u == pytest.approx(-10.0) and v == pytest.approx(0.0, abs=1e-9)
    # FROM south (180°) → toward north: v>0
    _, v = wind_uv(10.0, 180.0)
    assert v == pytest.approx(10.0)


# --- routes (cache swapped for a controlled loader; no live network) --------------------------
def test_storms_route_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = StormsResponse(storms=[parse_storm(SAMPLE_STORM)], as_of="2026-05-31T00:00:00+00:00",
                            source="NOAA NHC active storms", coverage="Atlantic + E/Central Pacific only.")

    async def _load() -> StormsResponse:
        return canned

    monkeypatch.setattr(storms_mod, "_cache", TTLCache(900.0, _load))
    res = client.get("/api/storms")
    assert res.status_code == 200
    body = res.json()
    assert len(body["storms"]) == 1 and body["storms"][0]["category"] == 1 and body["as_of"]


def test_storms_route_empty_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load() -> StormsResponse:
        return StormsResponse(storms=[], as_of="t", source="s", coverage="c")

    monkeypatch.setattr(storms_mod, "_cache", TTLCache(900.0, _load))
    res = client.get("/api/storms")
    assert res.status_code == 200 and res.json()["storms"] == []


def test_storms_route_upstream_failure_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> StormsResponse:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(storms_mod, "_cache", TTLCache(900.0, _boom))
    res = client.get("/api/storms")
    assert res.status_code == 502 and res.json()["code"] == "storms_provider_error"


def test_alerts_route_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load() -> AlertsResponse:
        return AlertsResponse(alerts=[parse_alert(SAMPLE_ALERT)], as_of="t",
                              source="NWS api.weather.gov active alerts", coverage="US only.")

    monkeypatch.setattr(alerts_mod, "_cache", TTLCache(900.0, _load))
    res = client.get("/api/alerts")
    assert res.status_code == 200
    body = res.json()
    assert body["alerts"][0]["event"] == "Tornado Warning" and body["alerts"][0]["geometry"]["type"] == "Polygon"


# --- helpers ----------------------------------------------------------------------------------
def storms_nhc_httpx():  # type: ignore[no-untyped-def]
    import storms.nhc as nhc_mod

    return nhc_mod.httpx


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_client(payload: dict):  # type: ignore[no-untyped-def]
    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
            return _FakeResp(payload)

    return lambda *a, **k: _FakeClient()
