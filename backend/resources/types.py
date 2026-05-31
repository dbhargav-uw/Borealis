"""The shared resource INPUT for site selection: long-term climatology over a grid.

Mirrors forecast/types.py (the operational act's EnsembleForecast), but the values are
multi-year ANNUAL MEANS per grid cell, not hourly ensemble members.
"""

from __future__ import annotations

from pydantic import BaseModel


class ResourceCell(BaseModel):
    """One grid cell: a location + its climatology annual means, keyed by provider
    variable name (e.g. {"ALLSKY_SFC_SW_DWN": 5.8, "WS50M": 7.1})."""

    lat: float
    lon: float
    values: dict[str, float]


class ResourceGrid(BaseModel):
    """A region's resource grid — the shared input every SuitabilityModel scores."""

    bbox: tuple[float, float, float, float]   # (lat_min, lon_min, lat_max, lon_max)
    resolution: float                          # degrees
    variables: list[str]
    cells: list[ResourceCell]

    @property
    def n_cells(self) -> int:
        return len(self.cells)
