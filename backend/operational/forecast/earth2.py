"""Earth2StudioProvider — future seam for self-hosted NVIDIA Earth2Studio
(AIFS-ENS + CorrDiff) behind the same ForecastProvider interface.

Out of scope for now (see CLAUDE.md "Out of scope"). Present only so the swap
point is real and obvious.
"""

from __future__ import annotations

from .base import ForecastProvider
from .types import EnsembleForecast


class Earth2StudioProvider(ForecastProvider):
    async def get_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        hours: int,
        variables: list[str],
    ) -> EnsembleForecast:
        raise NotImplementedError(
            "Earth2StudioProvider is a future seam — out of scope for the MVP."
        )
