"""
data/database.py

Async SQLAlchemy engine and session factory.
Provides the get_db FastAPI dependency and the session_factory
context manager used by the pipeline and Celery tasks.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from data.models.contract import Base

logger = logging.getLogger(__name__)

# Engine is module-level — created once at startup, shared across requests
_engine = None
_session_factory = None


def init_db(database_url: str, pool_size: int = 10, max_overflow: int = 20) -> None:
    """
    Initialise the engine. Called once at app startup.
    database_url must use the asyncpg driver:
        postgresql+asyncpg://user:pass@host/dbname
    """
    global _engine, _session_factory
    _engine = create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,     # Recycle dead connections
        echo=False,
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info(f"Database engine initialised: {database_url.split('@')[-1]}")


async def create_tables() -> None:
    """Create all tables. Used in tests and first-time setup."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables. Used in tests only."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ------------------------------------------------------------------
# Session dependency for FastAPI
# ------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency. Yields a session and commits/rolls back on exit.

    Usage:
        @router.post("/audit")
        async def audit(db: AsyncSession = Depends(get_db)):
            ...
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() at startup.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ------------------------------------------------------------------
# Context manager for Celery tasks and pipeline
# ------------------------------------------------------------------

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for use outside of FastAPI (pipeline, tasks).

    Usage:
        async with get_session() as db:
            result = await db.execute(...)
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() at startup.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
