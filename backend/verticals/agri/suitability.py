"""AgriSuitabilityModel — cropland siting from climatology. The SECOND vertical, proving
the platform principle: a new lens = one SuitabilityModel + a registration, nothing else.

A coarse agro-climatic ranking from annual means: growing-degree-days (base 10°C) scaled
by a water-adequacy factor (rainfed reference ~800 mm/yr, penalizing waterlogging). Like
the energy scores, this is a RELATIVE ranking comparator, not an agronomic yield model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from resources.constants import PRECIP, TEMP_2M
from verticals.base import SuitabilityModel, SuitabilityScore

if TYPE_CHECKING:
    from resources.types import ResourceCell

_GDD_BASE_C = 10.0
_DAYS = 365.0
_TARGET_PRECIP_MM = 800.0     # rainfed adequacy reference
_WATERLOG_MM = 2500.0         # excess rainfall above this starts to penalize


class AgriSuitabilityModel(SuitabilityModel):
    id = "agriculture"
    name = "Cropland siting"
    briefing_role = "agronomist"
    required_variables = [TEMP_2M, PRECIP]

    def metric_units(self, params: dict[str, Any]) -> str:
        return "GDD·yr (water-adjusted)"

    def score_cell(self, cell: ResourceCell, params: dict[str, Any]) -> SuitabilityScore:
        temp = cell.values[TEMP_2M]                       # °C, annual mean
        precip_mm = cell.values[PRECIP] * _DAYS           # mm/yr
        gdd = max(0.0, temp - _GDD_BASE_C) * _DAYS        # annual growing-degree-days, base 10°C

        if precip_mm <= _TARGET_PRECIP_MM:
            water = precip_mm / _TARGET_PRECIP_MM
        elif precip_mm <= _WATERLOG_MM:
            water = 1.0
        else:
            water = max(0.0, 1.0 - (precip_mm - _WATERLOG_MM) / _WATERLOG_MM)

        return SuitabilityScore(
            raw=gdd * water,
            metrics={
                "mean_temp_c": temp,
                "annual_precip_mm": precip_mm,
                "growing_degree_days": gdd,
                "water_factor": water,
            },
        )
