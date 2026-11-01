"""Structured logging with request correlation and secret redaction.

The project uses Loguru because it is already used throughout the pipeline.
In production the console and file sinks emit JSON so logs can be ingested by
Loki, CloudWatch, Datadog, or any other structured-log backend.
"""

from __future__ import annotations

import os
import re
import sys
from contextvars import ContextVar
from typing import Any

from loguru import logger

from clinical_trial_matcher.core.config import settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str] = ContextVar("user_id", default="-")

_SECRET_PATTERNS = (
    (re.compile(r"gsk_[A-Za-z0-9]{8,}"), "[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), r"\1[REDACTED]"),
    (
        re.compile(r"((?:password|secret|token|api[_-]?key)\s*[=:]\s*)\S+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
)

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def redact_text(value: str) -> str:
    """Remove credentials and common direct identifiers from a log string."""
    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    redacted = _EMAIL_PATTERN.sub("[EMAIL_REDACTED]", redacted)
    redacted = _PHONE_PATTERN.sub("[PHONE_REDACTED]", redacted)
    return redacted


def _redaction_filter(record: dict[str, Any]) -> bool:
    record["message"] = redact_text(str(record.get("message", "")))
    extra = record.get("extra") or {}
    for key, value in list(extra.items()):
        if isinstance(value, str):
            extra[key] = redact_text(value)
    return True


def _correlation_patcher(record: dict[str, Any]) -> dict[str, Any]:
    record["extra"].setdefault("request_id", request_id_ctx.get())
    record["extra"].setdefault("user_id", user_id_ctx.get())
    return record


def setup_logging() -> None:
    """Configure console and rotating file sinks exactly once per process."""
    logger.remove()

    # Windows consoles often default to cp1252, which cannot encode Loguru's
    # level icons. UTF-8 keeps structured logs portable across platforms.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass

    log_level = settings.log_level.upper()
    log_dir = os.getenv("LOG_DIR", "logs")
    if not settings.is_test:
        os.makedirs(log_dir, exist_ok=True)

    if settings.log_json_effective:
        logger.add(
            sys.stdout,
            level=log_level,
            serialize=True,
            filter=_redaction_filter,  # type: ignore[arg-type]
            enqueue=False,
        )
    else:
        logger.add(
            sys.stdout,
            level=log_level,
            colorize=True,
            filter=_redaction_filter,  # type: ignore[arg-type]
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{extra[request_id]}</cyan> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
                "<level>{message}</level>"
            ),
        )

    if not settings.is_test:
        logger.add(
            os.path.join(log_dir, "app.log"),
            level=log_level,
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            serialize=True,
            filter=_redaction_filter,  # type: ignore[arg-type]
            enqueue=True,
        )
        logger.add(
            os.path.join(log_dir, "errors.log"),
            level="ERROR",
            rotation="10 MB",
            retention="30 days",
            compression="zip",
            serialize=True,
            filter=_redaction_filter,  # type: ignore[arg-type]
            enqueue=True,
        )

    logger.configure(patcher=_correlation_patcher)  # type: ignore[arg-type]


# Backwards-compatible alias for the original entrypoint.
setup_logger = setup_logging
