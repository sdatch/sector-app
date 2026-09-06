"""
Comparison persistence + history + retention (PRD FR-6, user_model_spec §2.2).

The comparisons table is the durable form of the in-memory state store: terminal
resources land here, which makes history ("your past comparisons") a free query
and the deterministic cache a SQL lookup by cache_key later. Rows self-expire at
90 days; a daily purge task hard-deletes them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session_maker
from app.db.models import Comparison

RETENTION_DAYS = 90


async def persist_comparison(state) -> None:
    """Write a terminal comparison. Called from the orchestrator's finalize step
    (background task) with its own session — the request session is long gone."""
    resource = state.to_resource()
    created = state.generated_at
    row = Comparison(
        id=state.id,
        user_id=uuid.UUID(state.user_id),
        portfolio_id=uuid.UUID(state.portfolio_id) if state.portfolio_id else None,
        snapshot_id=state.snapshot.snapshot_id,
        request=resource.request.model_dump(mode="json"),
        result=resource.model_dump(mode="json"),
        status=resource.status.value,
        cache_key=state.cache_key,
        created_at=created,
        expires_at=created + timedelta(days=RETENTION_DAYS),
    )
    async with async_session_maker() as session:
        await session.merge(row)  # idempotent if finalize ever repeats
        await session.commit()


async def list_comparisons(
    session: AsyncSession, user_id: uuid.UUID, now: datetime, limit: int = 50
) -> list[Comparison]:
    result = await session.execute(
        select(Comparison)
        .where(Comparison.user_id == user_id, Comparison.expires_at > now)
        .order_by(Comparison.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_comparison_row(
    session: AsyncSession, user_id: uuid.UUID, comparison_id: uuid.UUID, now: datetime
) -> Comparison | None:
    result = await session.execute(
        select(Comparison).where(
            Comparison.id == comparison_id,
            Comparison.user_id == user_id,
            Comparison.expires_at > now,
        )
    )
    return result.scalar_one_or_none()


async def purge_expired(session: AsyncSession, now: datetime) -> int:
    """Hard-delete comparisons past expires_at (PRD FR-6, D4)."""
    result = await session.execute(
        delete(Comparison).where(Comparison.expires_at <= now)
    )
    await session.commit()
    return result.rowcount or 0
