"""OpenMeteoProvider — free Open-Meteo Ensemble API.

Phase 2 implements the real fetch (verify variable names against the live docs at
api.open-meteo.com/v1/ensemble before wiring them in).
"""

from __future__ import annotations

from .base import ForecastProvider
from .types import EnsembleForecast


class OpenMeteoProvider(ForecastProvider):
    def __init__(self, base_url: str = "https://api.open-meteo.com/v1/ensemble") -> None:
        self.base_url = base_url

    async def get_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        hours: int,
        variables: list[str],
    ) -> EnsembleForecast:
        raise NotImplementedError(
            "OpenMeteoProvider.get_ensemble_forecast lands in Phase 2."
        )
