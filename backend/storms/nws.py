"""NWS active tornado alerts — api.weather.gov/alerts/active (GeoJSON; REQUIRES a User-Agent header).

Two pulls: Tornado Warning + Tornado Watch. Warnings are storm-based polygons; watches are often
zone-based (geometry=null). Empty features is the NORMAL case (no active alert) — returns []. US-only.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from storms.types import AlertsResponse, WeatherAlert

NWS_SOURCE = "NWS api.weather.gov active alerts"
NWS_COVERAGE = "NWS — United States + territories only (no international coverage)."
TORNADO_EVENTS = ("Tornado Warning", "Tornado Watch")


def parse_alert(feature: dict) -> WeatherAlert:
    """Map one GeoJSON alert Feature → WeatherAlert (geometry kept verbatim; may be null)."""
    props = feature.get("properties") or {}
    return WeatherAlert(
        id=str(feature.get("id") or props.get("id") or ""),
        event=str(props.get("event", "")),
        severity=str(props.get("severity", "Unknown")),
        certainty=str(props.get("certainty", "Unknown")),
        urgency=str(props.get("urgency", "Unknown")),
        headline=props.get("headline"),
        area_desc=str(props.get("areaDesc", "")),
        issued_at=props.get("onset") or props.get("effective") or props.get("sent"),
        expires_at=props.get("expires") or props.get("ends"),
        geometry=feature.get("geometry"),
        source=NWS_SOURCE,
    )


def parse_alerts(payload: dict) -> list[WeatherAlert]:
    alerts: list[WeatherAlert] = []
    for feature in payload.get("features") or []:
        try:
            alerts.append(parse_alert(feature))
        except (KeyError, ValueError, TypeError):
            continue
    return alerts


async def build_alerts_response(base_url: str, user_agent: str) -> AlertsResponse:
    """Fetch tornado warnings + watches. Raises httpx.HTTPError / RuntimeError (→ 502 at the route)."""
    headers = {"User-Agent": user_agent, "Accept": "application/geo+json"}
    alerts: list[WeatherAlert] = []
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for event in TORNADO_EVENTS:
            resp = await client.get(base_url, params={"event": event})
            resp.raise_for_status()
            try:
                payload = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"NWS alerts response malformed: {exc}") from exc
            alerts.extend(parse_alerts(payload))
    return AlertsResponse(
        alerts=alerts,
        as_of=datetime.now(timezone.utc).isoformat(),
        source=NWS_SOURCE,
        coverage=NWS_COVERAGE,
    )
