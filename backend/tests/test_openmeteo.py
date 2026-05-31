"""OpenMeteoResourceProvider tests with a mocked httpx client (offline, deterministic).

Pins: the point-grid + MAX_CELLS cap, unit conversions to the semantic keys (MJ->kWh/day,
mm->mm/day, 10 m -> 50 m wind power law), the null/ocean drop, only-requested-variables
fetching (agri -> no hourly wind call), and multi-location batching.
"""

from __future__ import annotations

import asyncio
import math

import pytest

import resources.openmeteo as om_mod
from resources import select_resource_provider
from resources.constants import GHI, PRECIP, TEMP_2M, WIND_50M, WIND_SHEAR_ALPHA
from resources.openmeteo import OpenMeteoResourceProvider, _point_grid

CAPTURED: list[dict] = []

# Deterministic per-location window values (uniform across coords unless overridden by a client).
DAILY_VALUES = {
    "shortwave_radiation_sum": 18.0,   # MJ/m²/day -> /3.6 = 5.0 kWh/m²/day
    "temperature_2m_mean": 15.0,       # °C
    "precipitation_sum": 2.0,          # mm/day
}
WIND10_MS = 7.0                        # m/s @ 10 m -> *(5)^alpha @ 50 m


def _n_coords(params: dict) -> int:
    return len(str(params["latitude"]).split(","))


def _daily_block(om_vars: list[str]) -> dict:
    return {"daily": {"time": ["2021-01-01", "2021-01-02"], **{v: [DAILY_VALUES[v], DAILY_VALUES[v]] for v in om_vars}}}


def _wind_block() -> dict:
    return {"hourly": {"time": ["2021-01-01T00:00"], "wind_speed_10m": [WIND10_MS, WIND10_MS]}}


class _FakeResp:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _FakeClient:
    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
        params = params or {}
        CAPTURED.append(params)
        n = _n_coords(params)
        if "daily" in params:
            om_vars = params["daily"].split(",")
            return _FakeResp([_daily_block(om_vars) for _ in range(n)])
        return _FakeResp([_wind_block() for _ in range(n)])


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    CAPTURED.clear()
    monkeypatch.setattr(om_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient())


def test_grid_and_unit_conversions(patched: None) -> None:
    prov = OpenMeteoResourceProvider()
    # 0.2° box at 0.1° -> 3x3 = 9 points.
    grid = asyncio.run(
        prov.get_resource_grid((37.0, -122.0, 37.2, -121.8), 0.1, [GHI, TEMP_2M, WIND_50M])
    )
    assert grid.n_cells == 9
    cell = grid.cells[0]
    assert set(cell.values) == {GHI, TEMP_2M, WIND_50M}
    assert cell.values[GHI] == pytest.approx(5.0)                  # 18 MJ / 3.6
    assert cell.values[TEMP_2M] == pytest.approx(15.0)
    assert cell.values[WIND_50M] == pytest.approx(WIND10_MS * 5.0**WIND_SHEAR_ALPHA)
    # one daily + one hourly call (9 coords <= one batch).
    assert sum("daily" in p for p in CAPTURED) == 1
    assert sum("hourly" in p for p in CAPTURED) == 1
    assert all(p["models"] == "era5_seamless" for p in CAPTURED)


def test_only_requested_variables_fetched(patched: None) -> None:
    """Agriculture needs T2M+PRECIP only -> a daily call, NO hourly wind call."""
    prov = OpenMeteoResourceProvider()
    grid = asyncio.run(
        prov.get_resource_grid((37.0, -122.0, 37.1, -121.9), 0.1, [TEMP_2M, PRECIP])
    )
    assert grid.n_cells == 4
    for cell in grid.cells:
        assert set(cell.values) == {TEMP_2M, PRECIP}
        assert cell.values[PRECIP] == pytest.approx(2.0)
    assert any("daily" in p for p in CAPTURED)
    assert not any("hourly" in p for p in CAPTURED)   # no wind requested -> no hourly fetch


class _NullClient(_FakeClient):
    """The LAST coordinate of each block returns null arrays (ocean / no-data) -> dropped."""

    async def get(self, url: str, params: dict | None = None):  # type: ignore[no-untyped-def]
        params = params or {}
        CAPTURED.append(params)
        n = _n_coords(params)
        if "daily" in params:
            om_vars = params["daily"].split(",")
            blocks = [_daily_block(om_vars) for _ in range(n)]
            blocks[-1] = {"daily": {"time": ["2021-01-01"], **{v: [None] for v in om_vars}}}
            return _FakeResp(blocks)
        blocks = [_wind_block() for _ in range(n)]
        return _FakeResp(blocks)


def test_null_cell_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    CAPTURED.clear()
    monkeypatch.setattr(om_mod.httpx, "AsyncClient", lambda *a, **k: _NullClient())
    prov = OpenMeteoResourceProvider()
    grid = asyncio.run(prov.get_resource_grid((37.0, -122.0, 37.1, -121.9), 0.1, [TEMP_2M]))
    assert grid.n_cells == 3   # 4 points, last is null -> dropped
    assert all(not math.isnan(c.values[TEMP_2M]) for c in grid.cells)


def test_max_cells_cap() -> None:
    """A large/fine request coarsens until under the cap (cost guard) — pure grid math."""
    points, step = _point_grid((0.0, 0.0, 5.0, 5.0), 0.1, 400)
    assert len(points) <= 400
    assert step > 0.1   # had to coarsen from native


def test_empty_variables_raises(patched: None) -> None:
    prov = OpenMeteoResourceProvider()
    with pytest.raises(ValueError):
        asyncio.run(prov.get_resource_grid((37.0, -122.0, 37.1, -121.9), 0.1, []))


def test_select_provider_routes_by_size_and_resolution() -> None:
    small = (37.0, -122.0, 37.4, -121.6)   # 0.4° box
    large = (30.0, -120.0, 45.0, -100.0)   # 15°/20° box

    assert isinstance(
        select_resource_provider("auto", small, 0.1), OpenMeteoResourceProvider
    )
    assert isinstance(
        select_resource_provider("auto", large, 0.1), OpenMeteoResourceProvider
    )  # sub-0.5° resolution -> fine regardless of size
    # large + coarse -> NASA POWER
    from resources.nasapower import NASAPowerProvider

    assert isinstance(select_resource_provider("auto", large, 0.5), NASAPowerProvider)
    # explicit overrides the heuristic
    assert isinstance(
        select_resource_provider("open_meteo", large, 0.5), OpenMeteoResourceProvider
    )
    assert isinstance(
        select_resource_provider("nasa_power", small, 0.1), NASAPowerProvider
    )
