"""EnergySuitabilityModel — the 'energy' site-selection model, two lenses (solar / wind)
selected by params['lens']. Maps NASA POWER climatology annual means to a physical siting
metric per cell; the generic scoring layer normalizes + ranks across the region.

SOLAR: PVWatts-style annual specific yield from GHI with a temperature derate
       (kWh/kWp/yr). This is a fast, defensible RANKING comparator for a grid — NOT a
       bankable energy estimate. A full per-cell pvlib hourly simulation (reusing
       solar.py) is a documented richer upgrade.
WIND:  wind power density 0.5·ρ·v³ from the 50 m mean wind (W/m²) — defensible from a
       single mean; a Weibull capacity factor is a richer later option.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from resources.constants import GHI, TEMP_2M, WIND_50M
from verticals.base import SuitabilityModel, SuitabilityScore

if TYPE_CHECKING:
    from resources.types import ResourceCell

_AIR_DENSITY = 1.225        # kg/m³, sea-level standard
_HOURS_PER_YEAR = 8760.0
_DAYS_PER_YEAR = 365.0


def _lens(params: dict[str, Any]) -> str:
    lens = params.get("lens", "solar")
    if lens not in ("solar", "wind"):
        raise ValueError(
            f"energy suitability requires params.lens in {{'solar','wind'}}, got {lens!r}"
        )
    return lens


class EnergySuitabilityModel(SuitabilityModel):
    id = "energy"
    name = "Energy siting (solar / wind)"
    briefing_role = "renewable energy siting analyst"
    # Union across both lenses; the provider fetches all in one regional call.
    required_variables = [GHI, TEMP_2M, WIND_50M]

    def metric_units(self, params: dict[str, Any]) -> str:
        return "kWh/kWp/yr" if _lens(params) == "solar" else "W/m²"

    def score_cell(self, cell: ResourceCell, params: dict[str, Any]) -> SuitabilityScore:
        return self._solar(cell, params) if _lens(params) == "solar" else self._wind(cell, params)

    def _solar(self, cell: ResourceCell, params: dict[str, Any]) -> SuitabilityScore:
        ghi_daily = cell.values[GHI]                       # kWh/m²/day (annual mean)
        temp = cell.values.get(TEMP_2M, 25.0)              # °C
        base_pr = float(params.get("performance_ratio", 0.80))
        gamma_pdc = float(params.get("gamma_pdc", -0.004))  # 1/°C (cold => higher PR)
        pr = base_pr * (1.0 + gamma_pdc * (temp - 25.0))
        specific_yield = ghi_daily * _DAYS_PER_YEAR * pr   # kWh/kWp/yr
        return SuitabilityScore(
            raw=specific_yield,
            metrics={
                "mean_ghi_kwh_m2_day": ghi_daily,
                "specific_yield_kwh_kwp_yr": specific_yield,
                "capacity_factor": specific_yield / _HOURS_PER_YEAR,
                "mean_temp_c": temp,
            },
        )

    def _wind(self, cell: ResourceCell, params: dict[str, Any]) -> SuitabilityScore:
        v = cell.values[WIND_50M]                          # m/s @ 50 m (annual mean)
        rho = float(params.get("air_density", _AIR_DENSITY))
        wpd = 0.5 * rho * v**3                             # W/m²
        return SuitabilityScore(
            raw=wpd,
            metrics={"mean_wind_50m_ms": v, "wind_power_density_wm2": wpd},
        )
