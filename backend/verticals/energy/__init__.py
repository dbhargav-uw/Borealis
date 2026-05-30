"""Energy vertical — SHARED physics used by both acts.

solar.py (pvlib) and wind.py (numpy power curve) are imported by:
- the site-selection EnergySuitabilityModel (annual PV yield / wind power density), and
- the deferred operational EnergyModel (operational/, short-term MW fan).

The site-selection SuitabilityModel registers itself here in Phase 2; the operational
ImpactModel registers via the operational/ package.
"""

from __future__ import annotations
