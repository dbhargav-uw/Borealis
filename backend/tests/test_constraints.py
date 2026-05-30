"""Land/water mask constraint tests (offline; uses the bundled global-land-mask)."""

from __future__ import annotations

from constraints import apply_land_mask
from resources.types import ResourceCell, ResourceGrid


def _grid(coords: list[tuple[float, float]]) -> ResourceGrid:
    return ResourceGrid(
        bbox=(0.0, 0.0, 10.0, 10.0),
        resolution=0.5,
        variables=[],
        cells=[ResourceCell(lat=la, lon=lo, values={}) for la, lo in coords],
    )


def test_land_mask_drops_ocean() -> None:
    grid = _grid([(40.4, -3.7), (35.0, -40.0), (51.5, -0.1)])  # Madrid, mid-Atlantic, London
    kept = {(c.lat, c.lon) for c in apply_land_mask(grid).cells}
    assert (40.4, -3.7) in kept and (51.5, -0.1) in kept
    assert (35.0, -40.0) not in kept  # ocean dropped


def test_land_mask_empty_grid() -> None:
    grid = ResourceGrid(bbox=(0, 0, 10, 10), resolution=0.5, variables=[], cells=[])
    assert apply_land_mask(grid).cells == []
