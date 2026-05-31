"""Vertical-id -> model registries. The platform's plug point.

Two parallel registries, same id-uniqueness discipline:
- SUITABILITY (the current product): vertical id -> SuitabilityModel, used by /api/suitability.
- IMPACT (the deferred operational act): vertical id -> ImpactModel, used by
  /api/operational/assess. The same id (e.g. "energy") can appear in both — they're
  different registries — but must be unique within each.
"""

from __future__ import annotations

from verticals.base import ImpactModel, SuitabilityModel

_IMPACT: dict[str, ImpactModel] = {}
_SUITABILITY: dict[str, SuitabilityModel] = {}


# --- Impact (operational act) ---------------------------------------------------------


def register(model: ImpactModel) -> None:
    if model.id in _IMPACT:
        existing = type(_IMPACT[model.id]).__name__
        raise ValueError(
            f"Impact vertical id '{model.id}' is already registered (by {existing})."
        )
    _IMPACT[model.id] = model


def get_impact_model(vertical: str) -> ImpactModel:
    try:
        return _IMPACT[vertical]
    except KeyError as exc:
        raise KeyError(
            f"No ImpactModel registered for vertical '{vertical}'. Registered: {sorted(_IMPACT)}"
        ) from exc


def registered_verticals() -> list[str]:
    return sorted(_IMPACT)


# --- Suitability (site-selection product) ---------------------------------------------


def register_suitability(model: SuitabilityModel) -> None:
    if model.id in _SUITABILITY:
        existing = type(_SUITABILITY[model.id]).__name__
        raise ValueError(
            f"Suitability vertical id '{model.id}' is already registered (by {existing})."
        )
    _SUITABILITY[model.id] = model


def get_suitability_model(vertical: str) -> SuitabilityModel:
    try:
        return _SUITABILITY[vertical]
    except KeyError as exc:
        raise KeyError(
            f"No SuitabilityModel registered for vertical '{vertical}'. "
            f"Registered: {sorted(_SUITABILITY)}"
        ) from exc


def registered_suitability_verticals() -> list[str]:
    return sorted(_SUITABILITY)
