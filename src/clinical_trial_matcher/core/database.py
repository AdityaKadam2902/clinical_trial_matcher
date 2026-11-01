"""Async PostgreSQL connection using SQLAlchemy 2.0.

The application uses asyncpg for request-scoped queries. Alembic uses the
synchronous `DATABASE_URL_SYNC` URL in `alembic/env.py`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from clinical_trial_matcher.core.config import settings
from clinical_trial_matcher.db.base import Base

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo or settings.is_development,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session and commits on success."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create tables directly. Development/test only; use Alembic in production."""
    # Importing models registers them on Base.metadata.
    import clinical_trial_matcher.db.models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    logger.success("Database tables created/verified.")


async def close_db() -> None:
    """Dispose of the connection pool during application shutdown."""
    await engine.dispose()
    logger.info("Database connections closed.")
