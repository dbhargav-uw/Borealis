"""The ImpactModel interface and the cross-vertical types it produces/consumes.

An ImpactModel is the single pluggable piece per vertical: it maps an
EnsembleForecast + an Asset to an ImpactEnsemble (per-member series in the
vertical's units). Everything else in the spine is generic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # ImpactModel belongs to the deferred operational act; EnsembleForecast is only a
    # type hint here (annotations are lazy via `from __future__`), so no runtime coupling.
    from operational.forecast.types import EnsembleForecast


class Asset(BaseModel):
    """A located thing whose weather-risk we assess. `params` is vertical-specific
    (e.g. panel capacity for energy, crop + threshold for agriculture)."""

    name: str
    lat: float
    lon: float
    vertical: str
    params: dict[str, Any] = Field(default_factory=dict)


class ImpactEnsemble(BaseModel):
    """Per-member series in the vertical's units — the output of ImpactModel.apply.

    `series` is [member N][hour H] of the primary quantity (e.g. MW for energy).
    Verticals that derive several quantities can extend this later; the generic
    risk math operates on `series`.
    """

    units: str
    timestamps: list[datetime]
    series: list[list[float]]


class VerticalMeta(BaseModel):
    """Vertical-level metadata the generic briefing layer is parameterized by."""

    id: str
    name: str
    units: str
    briefing_role: str


class ImpactModel(ABC):
    """One per vertical. The forecast → domain-units mapping, plus metadata.

    Subclasses provide the five metadata fields (plain class attributes are fine —
    e.g. ``id = "energy"`` — they satisfy the abstract properties) and implement
    apply(). Declaring the metadata abstract means a subclass that forgets one
    cannot be instantiated, so omissions fail loudly at construction rather than
    silently AttributeError-ing later at meta() time.
    """

    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def units(self) -> str: ...

    @property
    @abstractmethod
    def required_variables(self) -> list[str]: ...

    @property
    @abstractmethod
    def briefing_role(self) -> str: ...

    @abstractmethod
    def apply(self, forecast: EnsembleForecast, asset: Asset) -> ImpactEnsemble:
        """Map the shared forecast for this asset into the vertical's units."""
        ...

    def meta(self) -> VerticalMeta:
        return VerticalMeta(
            id=self.id,
            name=self.name,
            units=self.units,
            briefing_role=self.briefing_role,
        )
