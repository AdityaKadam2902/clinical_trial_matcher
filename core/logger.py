"""
core/logger.py
──────────────
Centralized logging using Loguru.
Loguru automatically adds timestamp, level, file, function, and line number.
"""

import sys
from loguru import logger
from core.config import settings


def setup_logger():
    logger.remove()

    # Console output
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        level="DEBUG" if not settings.is_production else "INFO",
        colorize=True,
    )

    # File output — rotates at 10MB, keeps 7 days
    logger.add(
        "logs/clinical_trial_matcher.log",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    # Separate file for errors only
    logger.add(
        "logs/errors.log",
        rotation="10 MB",
        retention="30 days",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )

    return logger


setup_logger()
