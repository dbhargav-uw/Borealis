"""The shared forecast INPUT. Vertical-agnostic."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class EnsembleForecast(BaseModel):
    """N ensemble members of hourly weather at a single point.

    This is the shared input to every vertical. A forecast is a distribution,
    not a point — we carry all N members through so downstream code can compute
    real percentiles instead of collapsing to one number too early.
    """

    lat: float
    lon: float
    timestamps: list[datetime]                    # length H (hourly)
    members: int                                  # N
    variables: dict[str, list[list[float]]]       # var name -> [member N][hour H]

    @property
    def hours(self) -> int:
        return len(self.timestamps)
