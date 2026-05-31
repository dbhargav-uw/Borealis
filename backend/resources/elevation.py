"""Open-Meteo elevation — per-point terrain height (metres), free, no API key.

Used by the region site-search (/api/best-site) to compute a flood-exposure PENALTY per grid cell
(low-lying = higher illustrative flood risk). The per-LOCATION dossier flood read uses the precise
Cesium World Terrain height sampled in the frontend; this coarse global DEM (~90 m, GLO-90) is the
backend-side equivalent for scoring a whole region in one batched call. Failures degrade to None
(the caller treats unknown elevation as a neutral / no flood penalty).
"""

from __future__ import annotations

import httpx

OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
_MAX_PER_REQUEST = 100  # Open-Meteo caps the batch at 100 coordinates


async def fetch_elevations(
    points: list[tuple[float, float]],  # (lat, lon)
    *,
    url: str = OPEN_METEO_ELEVATION_URL,
) -> list[float | None]:
    """Batched terrain elevation (m) for each (lat, lon), request order preserved. On any transport
    or parse failure for a batch, that batch's entries come back as None (no flood penalty applied)."""
    out: list[float | None] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(points), _MAX_PER_REQUEST):
            chunk = points[i : i + _MAX_PER_REQUEST]
            params = {
                "latitude": ",".join(f"{lat:.4f}" for lat, _ in chunk),
                "longitude": ",".join(f"{lon:.4f}" for _, lon in chunk),
            }
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                elevations = resp.json().get("elevation")
                if isinstance(elevations, list) and len(elevations) == len(chunk):
                    out.extend(float(e) if isinstance(e, (int, float)) else None for e in elevations)
                else:
                    out.extend([None] * len(chunk))
            except (httpx.HTTPError, ValueError, TypeError):
                out.extend([None] * len(chunk))
    return out
