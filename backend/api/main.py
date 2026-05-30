"""Borealis API entry point.

/health (Phase 1) + POST /api/assess (Phase 2, the generic spine wired end-to-end).
Importing this module registers every active vertical's ImpactModel.
"""

from __future__ import annotations

import logging

import verticals.energy  # noqa: F401  -- import side-effect registers the 'energy' model
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.assess import router as assess_router
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

app.include_router(assess_router)


# Typed error bodies: { error, code?, ... } on every failure (project convention).
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    body = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "Invalid request body.",
            "code": "validation_error",
            "detail": jsonable_encoder(exc.errors()),
        },
    )


logger = logging.getLogger("borealis")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Backstop: any non-HTTPException still returns the typed {error, code} body
    # (never a plain-text 500). Log server-side; don't leak internals to the client.
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error.", "code": "internal_error"},
    )


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="borealis-api", version=app.version)
