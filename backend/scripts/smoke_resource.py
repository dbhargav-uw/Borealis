"""Live smoke test: real NASA POWER regional climatology -> ResourceGrid.

Run:  cd backend && uv run python scripts/smoke_resource.py

Proves the ResourceProvider on LIVE data (no HTTP server needed). Fetches a real grid
for a 4°x4° box (Colorado high plains) and prints the cell count + a few cells.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # backend/ on path

from resources import GHI, TEMP_2M, WIND_50M, get_resource_provider  # noqa: E402


async def main() -> None:
    provider = get_resource_provider()
    bbox = (40.0, -105.0, 44.0, -101.0)  # lat 40–44, lon -105..-101 (verified ~63 cells)
    variables = [GHI, WIND_50M, TEMP_2M]
    grid = await provider.get_resource_grid(bbox, resolution=0.5, variables=variables)

    print(f"=== NASA POWER climatology grid — bbox {bbox} ===")
    print(f"variables: {grid.variables}")
    print(f"cells: {grid.n_cells} (after dropping -999 no-data)")
    print(f"{'lat':>8}{'lon':>9}{'GHI':>8}{'WS50M':>8}{'T2M':>8}")
    for cell in grid.cells[:8]:
        v = cell.values
        print(f"{cell.lat:>8.3f}{cell.lon:>9.3f}{v[GHI]:>8.2f}{v[WIND_50M]:>8.2f}{v[TEMP_2M]:>8.2f}")
    assert grid.n_cells > 0, "expected a non-empty grid"
    print("\nOK — ResourceProvider ran on live NASA POWER data.")


if __name__ == "__main__":
    asyncio.run(main())
