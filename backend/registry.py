"""Maps a vertical id -> its ImpactModel. The whole platform's plug point.

Modules register themselves here; the API looks a model up by `vertical`. Energy
is registered in Phase 2, agriculture in Phase 5, insurance + logistics (stubs)
later.
"""

from __future__ import annotations

from verticals.base import ImpactModel

_REGISTRY: dict[str, ImpactModel] = {}


def register(model: ImpactModel) -> None:
    if model.id in _REGISTRY:
        existing = type(_REGISTRY[model.id]).__name__
        raise ValueError(
            f"Vertical id '{model.id}' is already registered (by {existing}); "
            "ids must be unique across verticals."
        )
    _REGISTRY[model.id] = model


def get_impact_model(vertical: str) -> ImpactModel:
    try:
        return _REGISTRY[vertical]
    except KeyError as exc:
        raise KeyError(
            f"No ImpactModel registered for vertical '{vertical}'. "
            f"Registered: {sorted(_REGISTRY)}"
        ) from exc


def registered_verticals() -> list[str]:
    return sorted(_REGISTRY)
