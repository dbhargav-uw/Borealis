"""Forecast layer: the shared weather INPUT, behind a swappable provider.

This package stays free of app/config imports so the forecast seam doesn't depend
on the FastAPI layer (dependencies point api -> forecast, never the reverse). The
api layer injects the configured base_url into get_provider().
"""

from __future__ import annotations

from .base import ForecastProvider
from .earth2 import Earth2StudioProvider
from .openmeteo import OpenMeteoProvider
from .types import EnsembleForecast

__all__ = [
    "EnsembleForecast",
    "ForecastProvider",
    "OpenMeteoProvider",
    "Earth2StudioProvider",
    "get_provider",
]


def get_provider(base_url: str | None = None) -> ForecastProvider:
    """The active provider for the MVP — Open-Meteo ensemble.

    base_url is injected by the api layer (from Settings); when omitted the
    provider falls back to its own default endpoint.
    """
    return OpenMeteoProvider() if base_url is None else OpenMeteoProvider(base_url=base_url)
