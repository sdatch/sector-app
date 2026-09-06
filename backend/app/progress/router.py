"""Progress trajectory endpoint (PRD FR-5 / U7)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_active_user
from app.db.base import get_async_session
from app.db.models import User

from .service import get_user_progress

router = APIRouter(prefix="/v1", tags=["progress"])


class ProgressPointOut(BaseModel):
    as_of: date
    total_value: float
    expected_return: float | None = None
    volatility: float | None = None


class ProgressSeries(BaseModel):
    portfolio_id: uuid.UUID
    points: list[ProgressPointOut]


@router.get("/progress", response_model=list[ProgressSeries])
async def get_progress(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ProgressSeries]:
    rows = await get_user_progress(session, user.id)
    by_portfolio: dict[uuid.UUID, list[ProgressPointOut]] = {}
    for r in rows:
        by_portfolio.setdefault(r.portfolio_id, []).append(
            ProgressPointOut(
                as_of=r.as_of,
                total_value=float(r.total_value),
                expected_return=r.metrics.get("expected_return"),
                volatility=r.metrics.get("volatility"),
            )
        )
    return [
        ProgressSeries(portfolio_id=pid, points=pts)
        for pid, pts in by_portfolio.items()
    ]
