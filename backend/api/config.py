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

    # Anthropic key for the briefing layer (Phase 3). Optional until then.
    anthropic_api_key: str | None = None

    # Frontend dev origin allowed through CORS.
    frontend_origin: str = "http://localhost:5173"

    # Open-Meteo ensemble endpoint (Phase 2 forecast provider).
    # NOTE: the ensemble API lives on the ensemble-api.* subdomain; the api.*
    # subdomain 404s for /v1/ensemble (verified live).
    open_meteo_base_url: str = "https://ensemble-api.open-meteo.com/v1/ensemble"


@lru_cache
def get_settings() -> Settings:
    return Settings()
