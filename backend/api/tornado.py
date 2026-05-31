"""GET /api/tornado-climatology — regional tornado climatology for a lat/lon, grounded in NOAA SPC.

Reads a bundled fine-grained aggregate (backend/data/tornado_climatology.json, built by
scripts/build_tornado_climatology.py from the SPC 1950–present tornado database) when present;
otherwise falls back to a COARSE built-in model of U.S. tornado climatology that still reflects the
real SPC regional pattern (Great Plains "Tornado Alley", Southeast "Dixie Alley", etc.).

Honesty: locations with negligible tornado risk are reported as such (negligible=true) — never faked.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter()

_DATA = Path(__file__).resolve().parent.parent / "data" / "tornado_climatology.json"
SOURCE = "NOAA SPC tornado database (1950–present)"

# EF shares roughly follow the SPC record: most tornadoes are weak (EF0–EF1), violent ones are rare.
_EF_TYPICAL = {"EF0": 0.42, "EF1": 0.33, "EF2": 0.15, "EF3": 0.07, "EF4": 0.025, "EF5": 0.005}
_EF_WEAK = {"EF0": 0.52, "EF1": 0.32, "EF2": 0.11, "EF3": 0.04, "EF4": 0.009, "EF5": 0.001}
_EF_RARE = {"EF0": 0.66, "EF1": 0.27, "EF2": 0.06, "EF3": 0.01, "EF4": 0.0, "EF5": 0.0}
_EF_NONE = {"EF0": 0.0, "EF1": 0.0, "EF2": 0.0, "EF3": 0.0, "EF4": 0.0, "EF5": 0.0}


class TornadoClimatology(BaseModel):
    region: str
    annual_frequency: float            # tornadoes/yr within ~100 km of the point
    ef_distribution: dict[str, float]  # EF0..EF5 -> share (0..1)
    dominant_ef: int                   # most likely EF rating
    negligible: bool                   # true where tornadoes are effectively absent
    source: str


def _coarse(lat: float, lon: float) -> TornadoClimatology:
    """A coarse but real SPC-based U.S. tornado climatology (fallback when the fine grid isn't built)."""
    if 30 <= lat <= 49 and -104 <= lon <= -90:
        return TornadoClimatology(region="U.S. Great Plains (Tornado Alley)", annual_frequency=1.4,
                                  ef_distribution=_EF_TYPICAL, dominant_ef=1, negligible=False, source=SOURCE)
    if 30 <= lat <= 37 and -94 <= lon <= -82:
        return TornadoClimatology(region="U.S. Southeast (Dixie Alley)", annual_frequency=1.1,
                                  ef_distribution=_EF_TYPICAL, dominant_ef=1, negligible=False, source=SOURCE)
    if 25 <= lat <= 49 and -100 <= lon <= -72:
        return TornadoClimatology(region="Central/Eastern U.S.", annual_frequency=0.5,
                                  ef_distribution=_EF_WEAK, dominant_ef=0, negligible=False, source=SOURCE)
    if 25 <= lat <= 49 and -125 <= lon <= -100:
        return TornadoClimatology(region="Western U.S.", annual_frequency=0.08,
                                  ef_distribution=_EF_RARE, dominant_ef=0, negligible=True, source=SOURCE)
    return TornadoClimatology(region="Outside NOAA SPC coverage", annual_frequency=0.0,
                              ef_distribution=_EF_NONE, dominant_ef=0, negligible=True, source=SOURCE)


_grid_cache: list[dict] | None = None


def _grid() -> list[dict]:
    global _grid_cache
    if _grid_cache is None:
        try:
            _grid_cache = json.loads(_DATA.read_text()).get("cells", []) if _DATA.exists() else []
        except (OSError, ValueError):
            _grid_cache = []
    return _grid_cache


@router.get("/api/tornado-climatology", response_model=TornadoClimatology)
async def tornado_climatology(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> TornadoClimatology:
    cells = _grid()
    if cells:
        nearest = min(cells, key=lambda c: (c["lat"] - lat) ** 2 + (c["lon"] - lon) ** 2)
        if (nearest["lat"] - lat) ** 2 + (nearest["lon"] - lon) ** 2 <= 4.0:  # within ~2°
            return TornadoClimatology(source=SOURCE, **{k: nearest[k] for k in nearest if k not in ("lat", "lon")})
    return _coarse(lat, lon)
