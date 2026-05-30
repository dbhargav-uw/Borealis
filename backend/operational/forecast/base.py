"""ForecastProvider — the swappable seam between Borealis and any forecast source.

OpenMeteoProvider (free Open-Meteo Ensemble API) is the MVP implementation;
Earth2StudioProvider is a future seam. Nothing downstream knows which is in use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import EnsembleForecast


class ForecastProvider(ABC):
    @abstractmethod
    async def get_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        hours: int,
        variables: list[str],
    ) -> EnsembleForecast:
        """Fetch N ensemble members of the requested hourly `variables`.

        `variables` is the union of every active vertical's required_variables,
        so a single forecast call feeds all verticals.
        """
        ...
