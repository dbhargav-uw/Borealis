"""Agriculture vertical — cropland suitability. Importing this package registers the
AgriSuitabilityModel in the suitability registry (import side-effect)."""

from __future__ import annotations

import registry

from .suitability import AgriSuitabilityModel

__all__ = ["AgriSuitabilityModel"]

registry.register_suitability(AgriSuitabilityModel())
