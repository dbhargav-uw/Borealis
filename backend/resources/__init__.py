"""Resource layer: the shared CLIMATOLOGY input for site selection, behind a swappable
provider. Two implementations:
- NASAPowerProvider — coarse (~0.5°), global incl. ocean, cheap; the default for large maps.
- OpenMeteoResourceProvider — fine (~0.1° ERA5-Land), land-only; for sub-region / fine siting.
`select_resource_provider` routes between them (explicit or `auto`)."""

from __future__ import annotations

from typing import Literal

from .base import ResourceProvider
from .constants import AUTO_FINE_MAX_SPAN_DEG, GHI, NATIVE_RESOLUTION_DEG, TEMP_2M, WIND_10M, WIND_50M
from .nasapower import NASAPowerProvider
from .openmeteo import OpenMeteoResourceProvider
from .types import ResourceCell, ResourceGrid

Source = Literal["auto", "nasa_power", "open_meteo"]

__all__ = [
    "ResourceProvider",
    "ResourceCell",
    "ResourceGrid",
    "NASAPowerProvider",
    "OpenMeteoResourceProvider",
    "get_resource_provider",
    "select_resource_provider",
    "Source",
    "GHI",
    "WIND_50M",
    "WIND_10M",
    "TEMP_2M",
]


def get_resource_provider(base_url: str | None = None) -> ResourceProvider:
    """The coarse global provider — NASA POWER climatology. base_url is injected by the api
    layer (from Settings); omit it to use the default endpoint."""
    return NASAPowerProvider() if base_url is None else NASAPowerProvider(base_url=base_url)


def _is_fine(bbox: tuple[float, float, float, float], resolution: float) -> bool:
    """`auto` heuristic: a sub-native resolution request, or a small region, wants fine data."""
    lat_min, lon_min, lat_max, lon_max = bbox
    max_span = max(lat_max - lat_min, lon_max - lon_min)
    return resolution < NATIVE_RESOLUTION_DEG or max_span <= AUTO_FINE_MAX_SPAN_DEG


def select_resource_provider(
    source: Source,
    bbox: tuple[float, float, float, float],
    resolution: float,
    *,
    nasa_power_base_url: str | None = None,
    open_meteo_archive_url: str | None = None,
    open_meteo_window: tuple[str, str] | None = None,
) -> ResourceProvider:
    """Pick the provider for one request. `auto` routes fine/small queries to Open-Meteo and
    large/coarse maps to NASA POWER; an explicit source forces that provider."""
    if source == "open_meteo" or (source == "auto" and _is_fine(bbox, resolution)):
        kwargs: dict[str, str] = {}
        if open_meteo_archive_url is not None:
            kwargs["archive_url"] = open_meteo_archive_url
        if open_meteo_window is not None:
            kwargs["window_start"], kwargs["window_end"] = open_meteo_window
        return OpenMeteoResourceProvider(**kwargs)
    return get_resource_provider(nasa_power_base_url)
