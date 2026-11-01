"""Shared rate limiter and client-IP resolution."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.core.logger import request_id_ctx


def rate_limit_key(request: Request) -> str:
    """Resolve the client key, honoring a configured number of trusted proxies."""
    if settings.trusted_proxy_count > 0:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
            if hops:
                index = -min(settings.trusted_proxy_count, len(hops))
                return hops[index]
    return get_remote_address(request)


_storage_uri = "memory://" if settings.is_development or settings.is_test else settings.redis_url

limiter = Limiter(
    key_func=rate_limit_key,
    default_limits=[settings.rate_limit_default] if settings.rate_limit_enabled else [],
    storage_uri=_storage_uri,
    enabled=settings.rate_limit_enabled,
    headers_enabled=False,
    swallow_errors=True,
    in_memory_fallback=[settings.rate_limit_default],
    in_memory_fallback_enabled=True,
)


async def rate_limit_exceeded_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    detail = getattr(exc, "detail", "Rate limit exceeded")
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limited",
                "message": str(detail),
                "request_id": request_id_ctx.get(),
            }
        },
        headers={"Retry-After": "60"},
    )
