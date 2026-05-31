"""Forecast-provider constants. Verified live against Open-Meteo on 2026-05-30."""

from __future__ import annotations

# The ensemble API is on a SEPARATE subdomain; api.open-meteo.com/v1/ensemble 404s.
ENSEMBLE_BASE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

# Default ensemble model for the MVP globe demo.
# gfs_seamless: 31 series (30 numbered members + the unsuffixed control), global ~25km,
# and — critically — it carries 100m hub-height wind AND all irradiance vars fully
# populated (verified). Swap to "ecmwf_ifs025" (51 members) for higher fidelity.
# NEVER default to icon_seamless / gem_global / bom_* — their wind_speed_100m is all-null.
DEFAULT_ENSEMBLE_MODEL = "gfs_seamless"
