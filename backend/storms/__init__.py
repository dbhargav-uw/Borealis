"""LIVE / OBSERVED storm feeds — a read-only sibling layer, SEPARATE from the illustrative
building-level hazard sim AND from the suitability spine (no ResourceProvider / SuitabilityModel here).

Two providers, both real and timestamped:
- `nhc` — NOAA NHC active tropical cyclones (CurrentStorms.json), Atlantic + E/Central Pacific only.
- `nws` — NWS active tornado warnings/watches (api.weather.gov alerts), US + territories only.

Empty feeds are the NORMAL case (off-season / no active alert) — never an error, never faked.
"""

from __future__ import annotations

from storms.nhc import build_storms_response
from storms.nws import build_alerts_response
from storms.types import ActiveStorm, AlertsResponse, StormsResponse, WeatherAlert

__all__ = [
    "ActiveStorm",
    "AlertsResponse",
    "StormsResponse",
    "WeatherAlert",
    "build_alerts_response",
    "build_storms_response",
]
