"""
core/database.py
────────────────
Async PostgreSQL connection using SQLAlchemy 2.0.
Uses asyncpg driver for high-performance async queries.
"""

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase
from core.config import settings
from loguru import logger


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=not settings.is_production,   # Log SQL in development
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,               # Test connections before using
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


async def get_db() -> AsyncSession:
    """
    FastAPI dependency — yields a database session.
    Automatically closes session after request completes.

    Usage in routes:
        @router.get("/")
        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise


async def create_tables():
    """Create all tables defined in models. Called at app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.success("Database tables created/verified.")


async def close_db():
    """Close database connections. Called at app shutdown."""
    await engine.dispose()
    logger.info("Database connections closed.")
