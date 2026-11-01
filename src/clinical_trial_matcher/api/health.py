"""Health, readiness, and metrics endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from clinical_trial_matcher import __version__
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.database import engine
from clinical_trial_matcher.core.rate_limit import limiter
from clinical_trial_matcher.core.redis import ping_redis

router = APIRouter(tags=["Health"])


@router.get("/health")
@limiter.exempt
async def health_check() -> dict:
    """Backwards-compatible aggregate health endpoint."""
    return {
        "status": "healthy",
        "version": __version__,
        "model": (settings.local_llm_model if settings.llm_provider == "local" else settings.groq_model_complex),
        "provider": settings.llm_provider,
        "environment": settings.app_env,
        "timestamp": time.time(),
    }


@router.get("/health/live")
@limiter.exempt
async def liveness() -> dict:
    """Liveness: the process is running and able to serve requests."""
    return {"status": "alive", "version": __version__}


@router.get("/health/ready")
@limiter.exempt
async def readiness() -> Response:
    """Readiness: dependencies required to serve traffic are available."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    if settings.rate_limit_enabled:
        checks["redis"] = "ok" if await ping_redis() else "unavailable"
    else:
        checks["redis"] = "disabled"

    dependency_failed = any(status == "unavailable" for status in checks.values())
    # Redis is mandatory in production, but development can run without it.
    if settings.is_development and checks.get("redis") == "unavailable":
        dependency_failed = checks.get("database") == "unavailable"

    payload = {
        "status": "ready" if not dependency_failed else "not_ready",
        "checks": checks,
        "version": __version__,
        "environment": settings.app_env,
    }
    return JSONResponse(
        content=payload,
        status_code=200 if not dependency_failed else 503,
    )


@router.get("/metrics", include_in_schema=False)
@limiter.exempt
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
