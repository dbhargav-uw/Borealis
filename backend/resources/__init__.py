"""Resource layer: the shared CLIMATOLOGY input for site selection, behind a swappable
provider (NASA POWER now, Global Wind/Solar Atlas GeoTIFF later)."""

from __future__ import annotations

from .base import ResourceProvider
from .constants import GHI, TEMP_2M, WIND_10M, WIND_50M
from .nasapower import NASAPowerProvider
from .types import ResourceCell, ResourceGrid

__all__ = [
    "ResourceProvider",
    "ResourceCell",
    "ResourceGrid",
    "NASAPowerProvider",
    "get_resource_provider",
    "GHI",
    "WIND_50M",
    "WIND_10M",
    "TEMP_2M",
]


def get_resource_provider(base_url: str | None = None) -> ResourceProvider:
    """The active provider for the MVP — NASA POWER climatology. base_url is injected by
    the api layer (from Settings); omit it to use the default endpoint."""
    return NASAPowerProvider() if base_url is None else NASAPowerProvider(base_url=base_url)
