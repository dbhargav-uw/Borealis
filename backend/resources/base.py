"""ResourceProvider — the swappable seam between Borealis and any climatology source.

NASAPowerProvider (free NASA POWER climatology) is the MVP; a Global Wind/Solar Atlas
GeoTIFF provider is a future seam behind the same interface. Nothing downstream knows
which is in use. (Parallels the operational ForecastProvider.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import ResourceGrid


class ResourceProvider(ABC):
    @abstractmethod
    async def get_resource_grid(
        self,
        bbox: tuple[float, float, float, float],   # (lat_min, lon_min, lat_max, lon_max)
        resolution: float,
        variables: list[str],
    ) -> ResourceGrid:
        """Fetch the climatology annual means for `variables` over the bbox.

        `variables` is the union of every active SuitabilityModel's required_variables,
        so a single call feeds all lenses.
        """
        ...
