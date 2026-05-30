"""Verticals — the ONLY place vertical-specific logic lives.

Each vertical is an ImpactModel that turns the shared forecast into its own
domain's units. Adding a vertical = writing one ImpactModel + registering it
(see registry.py). The energy module lands in Phase 2, agriculture in Phase 5;
insurance and logistics are stub-registered later.
"""

from __future__ import annotations

from .base import Asset, ImpactEnsemble, ImpactModel, VerticalMeta

__all__ = ["Asset", "ImpactEnsemble", "ImpactModel", "VerticalMeta"]
