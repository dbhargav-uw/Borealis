"""GENERIC siting constraints over a ResourceGrid. Like scoring/, this is vertical-agnostic
— it filters/masks cells, never touching domain logic.

The MVP constraint is a land/water mask: onshore-vs-offshore is the single most
decision-relevant filter for both solar and wind siting (NASA POWER also returns -999
over most open ocean, so the data partly self-masks). Offshore wind would relax this.
"""

from __future__ import annotations

import numpy as np
from global_land_mask import globe

from resources.types import ResourceGrid


def apply_land_mask(grid: ResourceGrid) -> ResourceGrid:
    """Return a copy of the grid keeping only land cells (drops ocean)."""
    if not grid.cells:
        return grid
    lats = np.array([c.lat for c in grid.cells], dtype=float)
    lons = np.array([c.lon for c in grid.cells], dtype=float)
    is_land = globe.is_land(lats, lons)
    kept = [cell for cell, land in zip(grid.cells, is_land) if bool(land)]
    return grid.model_copy(update={"cells": kept})
