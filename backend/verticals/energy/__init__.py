"""Energy vertical — SHARED physics + the site-selection suitability model.

solar.py (pvlib) and wind.py (numpy power curve) are imported by both the site-selection
EnergySuitabilityModel and the deferred operational EnergyModel (operational/).

Importing this package registers the EnergySuitabilityModel in the suitability registry
(import side-effect, mirroring how operational/ registers its ImpactModel).
"""

from __future__ import annotations

import registry

from .suitability import EnergySuitabilityModel

__all__ = ["EnergySuitabilityModel"]

registry.register_suitability(EnergySuitabilityModel())
