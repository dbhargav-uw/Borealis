"""GET /api/seasonal tests — mocked NASA POWER point climatology (offline)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import api.seasonal as seasonal_mod
from api.main import app

client = TestClient(app)

JAN_DEC = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _make_client(payload: dict):  # type: ignore[no-untyped-def]
    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
            return _FakeResp(payload)

    return lambda *a, **k: _FakeClient()


def test_seasonal_returns_twelve_months(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {m: 6.0 + i * 0.1 for i, m in enumerate(JAN_DEC)}
    payload = {"properties": {"parameter": {"WS50M": {**values, "ANN": 6.5}}}}
    monkeypatch.setattr(seasonal_mod.httpx, "AsyncClient", _make_client(payload))

    res = client.get("/api/seasonal", params={"lat": 37.0, "lon": -5.0, "variable": "WS50M"})
    assert res.status_code == 200
    body = res.json()
    assert body["variable"] == "WS50M" and body["units"] == "m/s"
    assert len(body["months"]) == 12
    assert body["months"][0] == pytest.approx(6.0)


def test_seasonal_replaces_fill_months(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {m: 5.0 for m in JAN_DEC}
    values["JUL"] = -999.0  # POWER fill -> replaced by the mean of valid months
    payload = {"properties": {"parameter": {"WS50M": {**values, "ANN": 5.0}}}}
    monkeypatch.setattr(seasonal_mod.httpx, "AsyncClient", _make_client(payload))

    body = client.get(
        "/api/seasonal", params={"lat": 1.0, "lon": 1.0, "variable": "WS50M"}
    ).json()
    assert all(m > 0 for m in body["months"])
    assert body["months"][6] == pytest.approx(5.0)  # filled with the valid-month mean


def test_seasonal_rejects_unknown_variable() -> None:
    res = client.get("/api/seasonal", params={"lat": 0.0, "lon": 0.0, "variable": "NOPE"})
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_variable"


def test_seasonal_upstream_failure_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BoomClient:
        async def __aenter__(self) -> "_BoomClient":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(seasonal_mod.httpx, "AsyncClient", lambda *a, **k: _BoomClient())
    res = client.get("/api/seasonal", params={"lat": 0.0, "lon": 0.0, "variable": "T2M"})
    assert res.status_code == 502
    assert res.json()["code"] == "resource_provider_error"
