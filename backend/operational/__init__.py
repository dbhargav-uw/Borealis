"""DEFERRED SECOND ACT — operational short-term variability for an ALREADY-CHOSEN site.

NOT part of the site-selection MVP path. This is the original operational pipeline:
Open-Meteo ForecastProvider -> EnergyModel (per-member MW fan) -> assess_risk
(P10/P50/P90 + threshold-crossing probabilities) -> POST /api/operational/assess.
It is the planned "click a chosen site -> its short-term generation variability" act —
kept importable, tested, and mounted, to be revived later. It SHARES
verticals/energy/solar.py and wind.py with the site-selection suitability model.

Importing this package registers the operational EnergyModel in the impact registry.
"""

from __future__ import annotations

import registry

from operational.energy import EnergyModel

__all__ = ["EnergyModel"]

registry.register(EnergyModel())
