"""End-to-end smoke test: real Open-Meteo ensemble -> EnergyModel -> assess_risk.

Run:  cd backend && uv run python scripts/smoke_assess.py

Proves the whole spine on LIVE data (no HTTP server needed). Prints members, the UTC
window, and the P10/P50/P90 generation fan for a solar plant and a wind farm.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # backend/ on path

import verticals.energy  # noqa: E402,F401  -- registers the energy model
from forecast import get_provider  # noqa: E402
from forecast.types import EnsembleForecast  # noqa: E402
from registry import get_impact_model  # noqa: E402
from risk import RiskAssessment, Threshold, assess_risk  # noqa: E402
from verticals.base import Asset  # noqa: E402


def _print_fan(
    label: str, fc: EnsembleForecast, risk: RiskAssessment, threshold_name: str
) -> None:
    print(f"\n=== {label} ===")
    print(f"location (grid-snapped): {fc.lat:.3f}, {fc.lon:.3f}")
    print(
        f"members: {fc.members}   hours: {fc.hours}   "
        f"window: {fc.timestamps[0]:%Y-%m-%d %H:%MZ} -> {fc.timestamps[-1]:%Y-%m-%d %H:%MZ}"
    )
    print(f"units: {risk.units}")
    print(f"{'hour (UTC)':<16}{'P10':>9}{'P50':>9}{'P90':>9}")
    for i in range(0, fc.hours, 3):  # every 3h, keep it short
        t = fc.timestamps[i]
        print(f"{t:%m-%d %H:%MZ}{'':<4}{risk.p10[i]:>9.2f}{risk.p50[i]:>9.2f}{risk.p90[i]:>9.2f}")
    tp = next((x for x in risk.thresholds if x.name == threshold_name), None)
    if tp is not None:
        print(
            f"P({threshold_name}) at any hour: {tp.prob_any:.0%}   "
            f"max hourly: {max(tp.prob_by_hour):.0%}"
        )
    assert all(a <= b <= c for a, b, c in zip(risk.p10, risk.p50, risk.p90)), "fan ordering violated"


async def main() -> None:
    model = get_impact_model("energy")
    provider = get_provider()

    # SOLAR — the deep pvlib slice: 100 MW DC plant in West Texas.
    solar = Asset(
        name="West Texas Solar", lat=31.9, lon=-102.1, vertical="energy",
        params={
            "kind": "solar", "dc_capacity_kw": 100000, "surface_tilt": 25,
            "surface_azimuth": 180, "gamma_pdc": -0.004, "system_loss": 0.14, "ac_dc_ratio": 1.2,
        },
    )
    fc_s = await provider.get_ensemble_forecast(solar.lat, solar.lon, 48, model.required_variables)
    risk_s = assess_risk(
        model.apply(fc_s, solar), [Threshold(name="below_bid_floor", direction="below", value=40.0)]
    )
    _print_fan("ENERGY / SOLAR — 100 MW DC, West Texas", fc_s, risk_s, "below_bid_floor")

    # WIND — power-curve path: 30 MW farm (10 x 3 MW) in the North Sea.
    wind = Asset(
        name="North Sea Wind", lat=54.0, lon=3.0, vertical="energy",
        params={"kind": "wind", "rated_power_kw": 3000, "n_turbines": 10},
    )
    fc_w = await provider.get_ensemble_forecast(wind.lat, wind.lon, 48, model.required_variables)
    risk_w = assess_risk(
        model.apply(fc_w, wind), [Threshold(name="below_10MW", direction="below", value=10.0)]
    )
    _print_fan("ENERGY / WIND — 30 MW farm, North Sea", fc_w, risk_w, "below_10MW")

    print("\nOK — full spine ran on live Open-Meteo data.")


if __name__ == "__main__":
    asyncio.run(main())
