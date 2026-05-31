"""Pydantic models for the LIVE storm feeds. Every model carries `source` + a timestamp — the
load-bearing differentiator from the illustrative (timeless, scenario) hazard sim."""

from __future__ import annotations

from pydantic import BaseModel


class ActiveStorm(BaseModel):
    id: str  # NHC storm id, e.g. "al062023"
    name: str
    basin: str  # AL / EP / CP
    classification: str  # NHC code: HU / TS / TD / STS / PTC / ...
    category: int  # Saffir–Simpson 0..5 (0 = tropical storm or weaker)
    lat: float
    lon: float
    max_wind_kt: float
    min_pressure_mb: float | None = None
    movement: str | None = None  # e.g. "NW at 12 mph"
    advisory_time: str  # NHC lastUpdate (ISO-8601)
    source: str
    # NOTE: past/forecast track + cone of uncertainty are a deferred fast-follow (NHC ships them
    # only as zipped shapefiles / KMZ). Added here later without a breaking change.


class StormsResponse(BaseModel):
    storms: list[ActiveStorm]
    as_of: str  # ISO-8601 UTC — when this layer last fetched the feed
    source: str
    coverage: str  # honest coverage limit


class WeatherAlert(BaseModel):
    id: str
    event: str  # "Tornado Warning" | "Tornado Watch" | ...
    severity: str  # Extreme / Severe / Moderate / Minor / Unknown
    certainty: str
    urgency: str
    headline: str | None = None
    area_desc: str  # affected counties (';'-joined)
    issued_at: str | None = None  # onset / effective
    expires_at: str | None = None  # expires / ends
    geometry: dict | None = None  # GeoJSON Polygon, or null (zone-based watches)
    source: str


class AlertsResponse(BaseModel):
    alerts: list[WeatherAlert]
    as_of: str  # ISO-8601 UTC
    source: str
    coverage: str
