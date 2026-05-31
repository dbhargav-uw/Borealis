"""NASA POWER constants. Verified live against the API on 2026-05-30."""

from __future__ import annotations

# Long-term CLIMATOLOGY, regional (bounding-box) endpoint — no API key, global,
# native ~0.5° grid (MERRA-2), returns monthly + ANNual (ANN) means.
NASA_POWER_BASE_URL = "https://power.larc.nasa.gov/api/temporal/climatology/regional"
# Point climatology endpoint (single lat/lon) — returns JAN–DEC + ANN; used for the
# per-site seasonal profile.
NASA_POWER_POINT_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
POWER_COMMUNITY = "RE"          # renewable energy community
POWER_FILL = -999.0             # POWER's no-data fill; cells carrying it are dropped

# Semantic name -> POWER parameter (annual mean), for SuitabilityModels to declare as
# required_variables. (The provider takes POWER parameter names directly.)
GHI = "ALLSKY_SFC_SW_DWN"       # all-sky surface shortwave down, kWh/m²/day
WIND_50M = "WS50M"              # wind speed at 50 m, m/s
WIND_10M = "WS10M"              # wind speed at 10 m, m/s
TEMP_2M = "T2M"                 # temperature at 2 m, °C
PRECIP = "PRECTOTCORR"          # bias-corrected total precipitation, mm/day

# A single regional request is capped at 10°×10° (verified). Larger regions are TILED into
# <=MAX_SPAN tiles by the provider; each axis must still be at least MIN_SPAN.
MIN_SPAN_DEG = 2.0
MAX_SPAN_DEG = 10.0
# Overall region cap (tiled) — bounds fan-out / cost. A 40° axis = up to 4 tiles.
MAX_REGION_SPAN_DEG = 40.0
NATIVE_RESOLUTION_DEG = 0.5

# --- Open-Meteo ERA5-Land archive (the FINE-resolution provider) ----------------------
# Multi-year reanalysis climatology at ~0.1°/~11 km, global, no API key. Carries the SAME
# semantic variables as POWER (GHI/temp/precip/wind) so SuitabilityModels are unchanged.
# Verified live against the archive docs on 2026-05-30.
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
# `era5_seamless` serves each variable at its finest native grid: temperature + 10 m wind from
# ERA5-Land (~0.1°/11 km), precipitation + shortwave from ERA5 (~0.25°/25 km). (ERA5-Land alone
# returns null for precip/radiation.) Ocean cells are removed downstream by the route land mask.
OPEN_METEO_MODEL = "era5_seamless"
OPEN_METEO_NATIVE_RES_DEG = 0.1         # finest grid spacing (temp/wind); precip/SWR are ~0.25°
OPEN_METEO_MAX_CELLS = 400              # hard cap on point fan-out per request (cost guard)
OPEN_METEO_COORDS_PER_REQUEST = 100     # multi-location batch size (comma-separated coords)
# Fixed multi-year climatology window (ISO dates). Short enough to be fast, long enough to be
# a stable ranking comparator. Both daily and hourly fetches share it.
OPEN_METEO_WINDOW_START = "2021-01-01"
OPEN_METEO_WINDOW_END = "2023-12-31"
# Wind shear power-law exponent for extrapolating the 10 m mean up to the 50 m hub the energy
# wind model expects (WIND_50M). α≈1/7 over open/rough terrain. Documented approximation.
WIND_SHEAR_ALPHA = 0.143
# `auto` provider selection: regions at or below this max-axis span (or any sub-0.5° request)
# route to the fine Open-Meteo provider; larger/coarser maps stay on cheap global NASA POWER.
AUTO_FINE_MAX_SPAN_DEG = 5.0
