"""Energy vertical: solar PV (pvlib) + wind power-curve behind one 'energy' ImpactModel.

Importing this package registers the model (import side-effect). api.main imports it at
startup so 'energy' is available to the registry.
"""

from __future__ import annotations

import registry

from .model import EnergyModel

__all__ = ["EnergyModel"]

registry.register(EnergyModel())
