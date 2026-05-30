"""Borealis API entry point.

Phase 1 exposes only /health (the endpoint the frontend hits to prove the two
halves are talking). POST /api/assess and the rest of the generic spine land in
later phases.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.config import get_settings

settings = get_settings()

app = FastAPI(title="Borealis API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="borealis-api", version=app.version)
