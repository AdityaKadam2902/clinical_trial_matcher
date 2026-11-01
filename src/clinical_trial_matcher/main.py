"""FastAPI application factory and entrypoint."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from clinical_trial_matcher import __version__
from clinical_trial_matcher.api.auth import router as auth_router
from clinical_trial_matcher.api.errors import register_exception_handlers
from clinical_trial_matcher.api.health import metrics as metrics_endpoint
from clinical_trial_matcher.api.health import router as health_router
from clinical_trial_matcher.api.middleware import (
    MaxBodySizeMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from clinical_trial_matcher.api.routes import router as api_router
from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.database import close_db, create_tables
from clinical_trial_matcher.core.logger import setup_logging
from clinical_trial_matcher.core.rate_limit import limiter, rate_limit_exceeded_handler
from clinical_trial_matcher.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Clinical Trial Matcher API version={} env={}", __version__, settings.app_env)
    logger.info("LLM provider={} model={}", settings.llm_provider, settings.local_llm_model)

    if settings.auto_create_tables and not settings.is_production:
        await create_tables()
        logger.warning("AUTO_CREATE_TABLES is enabled; use Alembic migrations in production")

    logger.success("Application ready.")
    try:
        yield
    finally:
        await close_redis()
        await close_db()
        logger.info("Application shutdown complete.")


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="Clinical Trial Matcher API",
        description="AI-powered clinical trial matching — 6-agent LangGraph pipeline",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled_effective else None,
        redoc_url="/redoc" if settings.docs_enabled_effective else None,
        openapi_url="/openapi.json" if settings.docs_enabled_effective else None,
    )

    register_exception_handlers(app)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # The last middleware added is the outermost layer. Request IDs must wrap
    # everything so that even rejected requests are correlated and logged.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Process-Time", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(MaxBodySizeMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    app.include_router(health_router, prefix="/api/v1")
    app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)
    app.include_router(auth_router)
    app.include_router(api_router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
    frontend_dir = os.path.abspath(frontend_dir)
    if os.path.exists(frontend_dir):
        assets_dir = os.path.join(frontend_dir, "assets")
        if os.path.exists(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            # Never serve the SPA shell for API or operational routes: unknown
            # endpoints must return a JSON 404 rather than a misleading 200.
            if (
                full_path == "api"
                or full_path.startswith("api/")
                or full_path in {"metrics", "docs", "redoc", "openapi.json"}
            ):
                return JSONResponse(
                    {"error": {"code": "not_found", "message": "Not found"}},
                    status_code=404,
                )

            index_path = os.path.join(frontend_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return JSONResponse({"error": "frontend not built"}, status_code=500)
    else:

        @app.get("/", include_in_schema=False)
        async def root():
            return {
                "message": "Clinical Trial Matcher API",
                "version": __version__,
                "docs": "/docs" if settings.docs_enabled_effective else None,
                "health": "/api/v1/health",
            }


app = create_app()
