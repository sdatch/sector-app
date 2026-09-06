"""
Async SQLAlchemy 2.0 engine + session (user_model_spec §2.1). Postgres in the
container/Railway; the models are portable so tests run on in-memory SQLite.

Boundary rule (§2.1): SQL holds user state only. Market data (snapshot
artifacts) never enters SQL — rows reference snapshot_id as an opaque string.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
