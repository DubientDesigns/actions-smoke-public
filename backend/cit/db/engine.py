"""Async SQLAlchemy engine/session factory for workers and the internal API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from cit.config import Settings, get_settings

_engine: AsyncEngine | None = None


def make_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    if settings.database_disable_prepared_statements:
        connect_args["prepare_threshold"] = None
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=5,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings())
    return _engine


def set_engine(engine: AsyncEngine | None) -> None:
    """Test hook."""
    global _engine
    _engine = engine


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncConnection]:
    async with get_engine().begin() as conn:
        yield conn
