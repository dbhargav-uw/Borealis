"""Briefing + 'ask the globe' tests. The Anthropic SDK is mocked — no network in CI."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

import api.suitability as suit_module
import briefing as brf
from api.main import app
from briefing import GlobeQuery, SiteBriefing
from resources.types import ResourceCell, ResourceGrid

client = TestClient(app)

SAMPLE = SiteBriefing(
    headline="Andalucía leads for solar",
    why_top_sites="The southern cells receive the most annual irradiance in the region.",
    top_drivers=["high GHI", "mild temperatures"],
    caveats=["These are climatology means, not bankable yield.", "Scores are relative to the region."],
    confidence="high",
)

REGION = {"lat_min": 36, "lon_min": -10, "lat_max": 44, "lon_max": 0}


# --- mock plumbing --------------------------------------------------------------------

class _FakeParsed:
    def __init__(self, out: object) -> None:
        self.parsed_output = out


class _FakeMessages:
    def __init__(self, out: object) -> None:
        self._out = out

    async def parse(self, **_: object) -> _FakeParsed:
        return _FakeParsed(self._out)


class _FakeAsyncClient:
    def __init__(self, out: object) -> None:
        self.messages = _FakeMessages(out)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeProvider:
    async def get_resource_grid(self, bbox: tuple, resolution: float, variables: list[str]) -> ResourceGrid:
        cells = [
            ResourceCell(lat=37.0, lon=-5.0, values={"ALLSKY_SFC_SW_DWN": 6.0, "T2M": 19, "WS50M": 5.0}),
            ResourceCell(lat=43.0, lon=-5.0, values={"ALLSKY_SFC_SW_DWN": 3.5, "T2M": 13, "WS50M": 9.0}),
        ]
        return ResourceGrid(bbox=bbox, resolution=resolution, variables=variables, cells=cells)


# --- generate_site_briefing -----------------------------------------------------------

def test_generate_no_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(brf.BriefingUnavailable):
        asyncio.run(
            brf.generate_site_briefing(
                region_label="x", lens="solar", metric_units="kWh/kWp/yr",
                ranked_sites=[{"rank": 1, "lat": 37.0, "lng": -5.0, "score": 1.0, "metrics": {}}],
                briefing_role="analyst", api_key=None,
            )
        )


def test_generate_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brf.anthropic, "AsyncAnthropic", lambda api_key=None: _FakeAsyncClient(SAMPLE))
    out = asyncio.run(
        brf.generate_site_briefing(
            region_label="Iberia", lens="solar", metric_units="kWh/kWp/yr",
            ranked_sites=[{"rank": 1, "lat": 37.0, "lng": -5.0, "score": 1.0, "metrics": {"x": 1.0}}],
            briefing_role="renewable energy siting analyst", api_key="test-key",
        )
    )
    assert out.confidence == "high"
    assert "Andalucía" in out.headline


def test_parse_query_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    gq = GlobeQuery(label="Spain", lat_min=36, lon_min=-9, lat_max=44, lon_max=3, lens="solar")
    monkeypatch.setattr(brf.anthropic, "AsyncAnthropic", lambda api_key=None: _FakeAsyncClient(gq))
    out = asyncio.run(brf.parse_globe_query(query="best solar in spain", api_key="test-key"))
    assert out.lens == "solar" and out.label == "Spain"


# --- routes ---------------------------------------------------------------------------

def test_suitability_briefing_null_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(suit_module, "get_resource_provider", lambda base_url=None: _FakeProvider())
    body = {"vertical": "energy", "region": REGION, "params": {"lens": "solar"}, "include_briefing": True}
    resp = client.post("/api/suitability", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["briefing"] is None  # degrades gracefully


def test_suitability_briefing_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(suit_module, "get_resource_provider", lambda base_url=None: _FakeProvider())

    async def _fake_brief(**_: object) -> SiteBriefing:
        return SAMPLE

    monkeypatch.setattr(suit_module, "generate_site_briefing", _fake_brief)
    body = {"vertical": "energy", "region": REGION, "params": {"lens": "solar"}, "include_briefing": True}
    data = client.post("/api/suitability", json=body).json()
    assert data["briefing"]["confidence"] == "high"
    assert "climatology" in data["briefing"]["caveats"][0].lower()


def test_ask_503_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post("/api/ask", json={"query": "best solar sites in spain"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "llm_unavailable"


def test_ask_mocked_clamps_bbox(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_parse(**_: object) -> GlobeQuery:
        # An oversized box (30°×20°) must be clamped to the 14° NL-search limit.
        return GlobeQuery(label="Iberia", lat_min=30, lon_min=-20, lat_max=50, lon_max=10, lens="wind")

    monkeypatch.setattr(suit_module, "parse_globe_query", _fake_parse)
    data = client.post("/api/ask", json={"query": "wind in iberia"}).json()
    assert data["lens"] == "wind" and data["label"] == "Iberia"
    r = data["region"]
    assert (r["lon_max"] - r["lon_min"]) <= 14.0 + 1e-9
    assert (r["lat_max"] - r["lat_min"]) <= 14.0 + 1e-9
