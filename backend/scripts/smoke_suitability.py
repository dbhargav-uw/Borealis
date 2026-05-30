"""Live smoke: NASA POWER climatology -> EnergySuitabilityModel -> score_and_rank.

Run:  cd backend && uv run python scripts/smoke_suitability.py

Proves the whole site-selection spine HEADLESS on live data. Fetches a real Iberia grid
and prints the top-5 candidate sites for both the solar and wind lenses.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # backend/ on path

import verticals.energy  # noqa: E402,F401  -- registers the EnergySuitabilityModel
from registry import get_suitability_model  # noqa: E402
from resources import get_resource_provider  # noqa: E402
from scoring import score_and_rank  # noqa: E402

_KEY_METRIC = {
    "solar": "specific_yield_kwh_kwp_yr",
    "wind": "wind_power_density_wm2",
}


async def main() -> None:
    model = get_suitability_model("energy")
    provider = get_resource_provider()
    bbox = (36.0, -10.0, 44.0, 0.0)  # Iberian peninsula
    grid = await provider.get_resource_grid(bbox, resolution=0.5, variables=model.required_variables)
    print(f"Iberia climatology grid: {grid.n_cells} cells")

    for lens in ("solar", "wind"):
        scores = model.score_grid(grid, {"lens": lens})
        result = score_and_rank(grid, scores, top_n=5, metric_units=model.metric_units({"lens": lens}))
        metric = _KEY_METRIC[lens]
        print(f"\n=== {lens.upper()} — top 5 sites (units: {result.metric_units}) ===")
        for s in result.ranked_sites:
            print(f"  #{s.rank}  ({s.lat:6.2f},{s.lon:7.2f})  score={s.score:.3f}  {metric}={s.metrics[metric]:.1f}")
        assert all(0.0 <= c.score <= 1.0 for c in result.cells), "scores must be in [0,1]"

    print("\nOK — site-selection spine ran headless on live NASA POWER data.")


if __name__ == "__main__":
    asyncio.run(main())
