"""NASAPowerProvider tests with a mocked httpx client (offline, deterministic).

Pins the one-param-per-call fan-out + (lat,lon) inner-join, the -999 no-data drop, the
request params (community=RE, JSON, bbox), and the bbox-span guard.
"""

from __future__ import annotations

import asyncio

import pytest

import resources.nasapower as np_mod
from resources.nasapower import NASAPowerProvider

# 2x2 native-ish grid; the 4th GHI cell is -999 (no-data) and must be dropped.
COORDS = [(40.25, -104.75), (40.25, -104.25), (40.75, -104.75), (40.75, -104.25)]
PARAM_VALUES = {
    "ALLSKY_SFC_SW_DWN": [5.0, 5.5, 6.0, -999.0],
    "WS50M": [7.0, 7.5, 8.0, 8.5],
}
CAPTURED: list[dict] = []


def _feature_collection(param: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"parameter": {param: {"ANN": val, "JAN": val}}},
            }
            for (lat, lon), val in zip(COORDS, PARAM_VALUES[param])
        ],
    }


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
        params = params or {}
        CAPTURED.append(params)
        return _FakeResp(_feature_collection(params["parameters"]))


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    CAPTURED.clear()
    monkeypatch.setattr(np_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient())


def test_join_and_clean(patched: None) -> None:
    prov = NASAPowerProvider()
    grid = asyncio.run(
        prov.get_resource_grid((40.0, -105.0, 44.0, -101.0), 0.5, ["ALLSKY_SFC_SW_DWN", "WS50M"])
    )
    assert grid.n_cells == 3  # the -999 GHI cell is dropped
    for cell in grid.cells:
        assert set(cell.values) == {"ALLSKY_SFC_SW_DWN", "WS50M"}
        assert cell.values["ALLSKY_SFC_SW_DWN"] != -999.0
    # one GET per parameter (fan-out), with the right query params
    assert {p["parameters"] for p in CAPTURED} == {"ALLSKY_SFC_SW_DWN", "WS50M"}
    assert all(p["community"] == "RE" and p["format"] == "JSON" for p in CAPTURED)
    assert all("latitude-min" in p and "longitude-max" in p for p in CAPTURED)


def test_bad_span_raises(patched: None) -> None:
    prov = NASAPowerProvider()
    with pytest.raises(ValueError, match="span"):  # lat span 1° (too small)
        asyncio.run(prov.get_resource_grid((40.0, -105.0, 41.0, -101.0), 0.5, ["WS50M"]))
    with pytest.raises(ValueError, match="span"):  # lon span 35° (too big)
        asyncio.run(prov.get_resource_grid((40.0, -105.0, 44.0, -70.0), 0.5, ["WS50M"]))


def test_empty_variables_raises(patched: None) -> None:
    prov = NASAPowerProvider()
    with pytest.raises(ValueError):
        asyncio.run(prov.get_resource_grid((40.0, -105.0, 44.0, -101.0), 0.5, []))
