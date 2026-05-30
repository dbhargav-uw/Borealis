"""NASA POWER constants. Verified live against the API on 2026-05-30."""

from __future__ import annotations

# Long-term CLIMATOLOGY, regional (bounding-box) endpoint — no API key, global,
# native ~0.5° grid (MERRA-2), returns monthly + ANNual (ANN) means.
NASA_POWER_BASE_URL = "https://power.larc.nasa.gov/api/temporal/climatology/regional"
POWER_COMMUNITY = "RE"          # renewable energy community
POWER_FILL = -999.0             # POWER's no-data fill; cells carrying it are dropped

# Semantic name -> POWER parameter (annual mean), for SuitabilityModels to declare as
# required_variables. (The provider takes POWER parameter names directly.)
GHI = "ALLSKY_SFC_SW_DWN"       # all-sky surface shortwave down, kWh/m²/day
WIND_50M = "WS50M"              # wind speed at 50 m, m/s
WIND_10M = "WS10M"              # wind speed at 10 m, m/s
TEMP_2M = "T2M"                 # temperature at 2 m, °C

# Regional endpoint accepts a bbox between these spans per axis (verified: 1° too small,
# 30° too big; a single regional request is capped at 10°×10°).
MIN_SPAN_DEG = 2.0
MAX_SPAN_DEG = 10.0
NATIVE_RESOLUTION_DEG = 0.5
