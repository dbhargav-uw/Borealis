"""Application settings, loaded from the repo-root .env (or process env).

Secrets live only in .env (never committed). Everything here has a safe default
so the app boots with no .env present (Phase 1) — ANTHROPIC_API_KEY stays None
until the briefing layer (Phase 3) needs it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/api/config.py -> parents[2] == repo root (where .env lives).
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Prefer a backend-local .env, then fall back to the repo-root .env.
        env_file=(_REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic key for the "why this site" briefing + NL search (P4). Optional — the
    # product works without it (briefing degrades to null).
    anthropic_api_key: str | None = None
    briefing_model: str = "claude-sonnet-4-6"

    # Frontend dev origin allowed through CORS.
    frontend_origin: str = "http://localhost:5173"

    # NASA POWER regional climatology endpoint — the COARSE (~0.5°) global resource provider.
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api/temporal/climatology/regional"

    # Open-Meteo ERA5-Land archive endpoint — the FINE (~0.1°) resource provider for
    # sub-region / high-resolution siting. Distinct from the ensemble URL below.
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"
    # Climatology window for the fine provider (ISO dates; overridable for faster/slower fetches).
    open_meteo_window_start: str = "2021-01-01"
    open_meteo_window_end: str = "2023-12-31"

    # Open-Meteo ensemble endpoint — DEFERRED operational act (/api/operational/assess).
    # The ensemble API lives on the ensemble-api.* subdomain (api.* 404s).
    open_meteo_base_url: str = "https://ensemble-api.open-meteo.com/v1/ensemble"

    # Open-Meteo STANDARD forecast endpoint — the LIVE current global wind grid (/api/current-wind).
    # Distinct from the ensemble + archive URLs above; supports `current=` + multi-point batches.
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"

    # LIVE / OBSERVED storm feeds (read-only; SEPARATE from the illustrative sim + the suitability spine).
    # NHC = Atlantic + E/Central Pacific cyclones; NWS = US tornado alerts (requires a User-Agent).
    nhc_current_storms_url: str = "https://www.nhc.noaa.gov/CurrentStorms.json"
    nws_alerts_url: str = "https://api.weather.gov/alerts/active"
    nws_user_agent: str = "Borealis (rishboss0@gmail.com)"
    storms_cache_ttl_seconds: float = 900.0
    # Coarse global lattice (degrees) for the live wind-flow layer + its OWN long cache. Open-Meteo's
    # free tier is location-weighted (each grid point ≈ one "call", capped ~600/min, 10k/day, and the GET
    # URL 414s above ~700 points). 12° (15×30 = 450 cells) fetches in ≤2 small calls, fits every limit,
    # and cesium-wind-layer interpolates it into a smooth global flow. Cached for HOURS (synoptic wind
    # persists, so "current, refreshed ~3-hourly" is honest). Finer needs paced fetching (see current_wind.py).
    current_wind_resolution: float = 12.0
    current_wind_cache_ttl_seconds: float = 10800.0  # 3 h


@lru_cache
def get_settings() -> Settings:
    return Settings()
