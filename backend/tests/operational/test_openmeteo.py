"""OpenMeteoProvider tests with a mocked httpx client (offline, deterministic).

Pins the member-decode contract (unsuffixed base = control = member 0), the request
params (GMT + m/s + gfs_seamless), interior-null forward-fill, and the all-null guard.
"""

from __future__ import annotations

import asyncio

import pytest

import operational.forecast.openmeteo as om
from operational.forecast.openmeteo import OpenMeteoProvider

CAPTURED: dict[str, dict] = {}


def _payload() -> dict:
    return {
        "latitude": 51.5,
        "longitude": -0.125,
        "hourly": {
            "time": ["2026-05-30T00:00", "2026-05-30T01:00", "2026-05-30T02:00"],
            # control (unsuffixed) has an interior null -> must be forward-filled.
            "temperature_2m": [10.0, None, 12.0],
            "temperature_2m_member01": [11.0, 11.5, 12.0],
            "temperature_2m_member02": [9.0, 9.5, 10.0],
            "wind_speed_10m": [3.0, 3.0, 3.0],
            "wind_speed_10m_member01": [4.0, 4.0, 4.0],
            "wind_speed_10m_member02": [5.0, 5.0, 5.0],
            # all-null variable to exercise the guard.
            "wind_speed_100m": [None, None, None],
            "wind_speed_100m_member01": [None, None, None],
        },
    }


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
        CAPTURED["url"] = url
        CAPTURED["params"] = params or {}
        return _FakeResp(self._payload)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    CAPTURED.clear()
    payload = _payload()
    monkeypatch.setattr(om.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))


def test_member_decode_and_forward_fill(patched: None) -> None:
    prov = OpenMeteoProvider()
    fc = asyncio.run(prov.get_ensemble_forecast(51.5, -0.12, 3, ["temperature_2m", "wind_speed_10m"]))

    assert fc.members == 3                    # control + member01 + member02
    assert fc.hours == 3
    # member index 0 == the unsuffixed control series, with the None forward-filled.
    assert fc.variables["temperature_2m"][0] == [10.0, 10.0, 12.0]
    assert fc.variables["temperature_2m"][1] == [11.0, 11.5, 12.0]
    assert fc.variables["wind_speed_10m"][2] == [5.0, 5.0, 5.0]
    # tz-aware UTC timestamps.
    assert fc.timestamps[0].utcoffset().total_seconds() == 0


def test_request_params_are_si_and_gfs(patched: None) -> None:
    prov = OpenMeteoProvider()
    asyncio.run(prov.get_ensemble_forecast(51.5, -0.12, 48, ["temperature_2m"]))
    p = CAPTURED["params"]
    assert p["models"] == "gfs_seamless"
    assert p["timezone"] == "GMT"
    assert p["wind_speed_unit"] == "ms"
    assert p["forecast_days"] == 2            # ceil(48/24)
    assert p["hourly"] == "temperature_2m"


def test_all_null_variable_raises(patched: None) -> None:
    prov = OpenMeteoProvider()
    with pytest.raises(RuntimeError, match="all-null"):
        asyncio.run(prov.get_ensemble_forecast(51.5, -0.12, 3, ["wind_speed_100m"]))


def test_missing_required_variable_raises(patched: None) -> None:
    prov = OpenMeteoProvider()
    with pytest.raises(RuntimeError, match="did not return"):
        asyncio.run(prov.get_ensemble_forecast(51.5, -0.12, 3, ["cloud_cover"]))


def test_leading_null_is_back_filled(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "latitude": 1.0,
        "longitude": 2.0,
        "hourly": {
            "time": ["2026-05-30T00:00", "2026-05-30T01:00"],
            "temperature_2m": [None, 5.0],  # leading null -> back-filled from next
            "temperature_2m_member01": [6.0, 7.0],
        },
    }
    monkeypatch.setattr(om.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    fc = asyncio.run(OpenMeteoProvider().get_ensemble_forecast(1.0, 2.0, 2, ["temperature_2m"]))
    assert fc.variables["temperature_2m"][0] == [5.0, 5.0]


def test_single_all_null_member_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # The variable HAS data (control), but one member series is entirely null.
    payload = {
        "latitude": 1.0,
        "longitude": 2.0,
        "hourly": {
            "time": ["2026-05-30T00:00", "2026-05-30T01:00"],
            "temperature_2m": [1.0, 2.0],
            "temperature_2m_member01": [None, None],
        },
    }
    monkeypatch.setattr(om.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    with pytest.raises(RuntimeError, match="cannot clean"):
        asyncio.run(OpenMeteoProvider().get_ensemble_forecast(1.0, 2.0, 2, ["temperature_2m"]))


def test_malformed_response_becomes_runtimeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    # Missing 'latitude' -> KeyError inside decode -> surfaced as RuntimeError (-> 502).
    payload = {
        "hourly": {"time": ["2026-05-30T00:00"], "temperature_2m": [1.0]},
    }
    monkeypatch.setattr(om.httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))
    with pytest.raises(RuntimeError, match="malformed"):
        asyncio.run(OpenMeteoProvider().get_ensemble_forecast(1.0, 2.0, 1, ["temperature_2m"]))
