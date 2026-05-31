"""Live smoke test: real Open-Meteo ERA5-Land climatology -> fine ResourceGrid.

Run:  cd backend && uv run python scripts/smoke_openmeteo.py

Proves the FINE provider on LIVE data (no HTTP server needed). Fetches a small box east of
San Jose at 0.1° — a region the coarse NASA POWER provider can't even represent — and prints
the cell count + a few cells in the semantic keys/units.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # backend/ on path

from resources import GHI, TEMP_2M, WIND_50M  # noqa: E402
from resources.openmeteo import OpenMeteoResourceProvider, point_monthly_climatology  # noqa: E402


async def main() -> None:
    provider = OpenMeteoResourceProvider()
    bbox = (37.2, -121.8, 37.6, -121.4)   # ~0.4° box east of San Jose (Diablo Range)
    variables = [GHI, WIND_50M, TEMP_2M]
    grid = await provider.get_resource_grid(bbox, resolution=0.1, variables=variables)

    print(f"=== Open-Meteo ERA5 (seamless) grid — bbox {bbox} @ 0.1° ===")
    print(f"variables: {grid.variables}")
    print(f"effective step: {grid.resolution:.3f}°   cells: {grid.n_cells} (after null/ocean drop)")
    print(f"{'lat':>8}{'lon':>9}{'GHI':>8}{'WS50M':>8}{'T2M':>8}")
    for cell in grid.cells[:8]:
        v = cell.values
        print(f"{cell.lat:>8.3f}{cell.lon:>9.3f}{v[GHI]:>8.2f}{v[WIND_50M]:>8.2f}{v[TEMP_2M]:>8.2f}")
    assert grid.n_cells > 0, "expected a non-empty fine grid"

    months = await point_monthly_climatology(37.4, -121.6, GHI)
    print(f"\nseasonal GHI (kWh/m²/day) JAN..DEC @ 37.4,-121.6: "
          f"{None if months is None else [round(m, 1) for m in months]}")
    print("\nOK — OpenMeteoResourceProvider ran on live ERA5-Land data.")


if __name__ == "__main__":
    asyncio.run(main())
