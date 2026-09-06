"""
Per-portfolio progress (PRD FR-5 / U7). On snapshot rotation, value every
portfolio at the new snapshot and append a progress_point — users get a value +
risk trajectory with zero effort. No cost basis / P&L (PRD non-goal).

The trajectory is reconstructed from the snapshot's own daily sector-return
series (which IS real history) valued at the portfolio's current weights, so a
fresh portfolio has a meaningful chart immediately, and each rotation extends it
by a day.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Portfolio, ProgressPoint
from app.portfolios.service import list_portfolios, portfolio_sector_weights
from app.snapshots.artifacts import SnapshotBundle

_TRADING_DAYS = 252
_TRAIL = 21  # trailing window for point-in-time risk metrics


def _weights_vector(portfolio: Portfolio, bundle: SnapshotBundle) -> np.ndarray:
    sectors = bundle.artifacts.sectors
    idx = {s: i for i, s in enumerate(sectors)}
    w = np.zeros(len(sectors))
    weights = portfolio_sector_weights(
        portfolio, bundle.ticker_price, bundle.fund_composition
    )
    for sector, weight in weights.items():
        if sector in idx:
            w[idx[sector]] = weight
    return w


def _current_value(portfolio: Portfolio, bundle: SnapshotBundle) -> float:
    if portfolio.source == "manual":
        return 100_000.0  # nominal base for weight-only portfolios
    total = 0.0
    for p in portfolio.positions:
        total += float(p.quantity) * bundle.ticker_price.get(p.ticker, 0.0)
    return total or 100_000.0


def _business_days_ending(end: date, n: int) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return list(reversed(days))


def compute_trajectory(
    portfolio: Portfolio, bundle: SnapshotBundle, window_days: int = 90
) -> list[tuple[date, float, dict]]:
    """Return [(as_of, total_value, metrics)] for the last `window_days`."""
    a = bundle.artifacts
    w = _weights_vector(portfolio, bundle)
    if w.sum() <= 0:
        return []

    daily = a.sector_returns @ w  # (T,) portfolio daily returns
    n = min(window_days, len(daily))
    idx_full = np.cumprod(1.0 + daily)
    current = _current_value(portfolio, bundle)

    tail = slice(len(daily) - n, len(daily))
    idx_tail = idx_full[tail]
    values = current * idx_tail / idx_full[-1]
    dates = _business_days_ending(a.meta.prices_end, n)

    out: list[tuple[date, float, dict]] = []
    for k in range(n):
        t = len(daily) - n + k
        lo = max(0, t - _TRAIL)
        window = daily[lo : t + 1]
        vol = float(window.std(ddof=1) * np.sqrt(_TRADING_DAYS)) if window.size > 1 else 0.0
        mean = float(window.mean() * _TRADING_DAYS) if window.size else 0.0
        out.append(
            (
                dates[k],
                round(float(values[k]), 2),
                {"expected_return": round(mean, 4), "volatility": round(vol, 4)},
            )
        )
    return out


async def store_trajectory(
    session: AsyncSession,
    user_id: uuid.UUID,
    portfolio: Portfolio,
    bundle: SnapshotBundle,
    window_days: int = 90,
) -> int:
    points = compute_trajectory(portfolio, bundle, window_days)
    for as_of, value, metrics in points:
        await session.merge(
            ProgressPoint(
                user_id=user_id,
                portfolio_id=portfolio.id,
                as_of=as_of,
                total_value=value,
                metrics=metrics,
            )
        )
    await session.commit()
    return len(points)


async def run_progress_for_all(
    session: AsyncSession, bundle: SnapshotBundle, window_days: int = 90
) -> int:
    """Value every portfolio of every user and append points. Idempotent."""
    result = await session.execute(select(Portfolio))
    total = 0
    for portfolio in result.scalars().all():
        total += await store_trajectory(
            session, portfolio.user_id, portfolio, bundle, window_days
        )
    return total


async def get_user_progress(
    session: AsyncSession, user_id: uuid.UUID
) -> list[ProgressPoint]:
    result = await session.execute(
        select(ProgressPoint)
        .where(ProgressPoint.user_id == user_id)
        .order_by(ProgressPoint.portfolio_id, ProgressPoint.as_of)
    )
    return list(result.scalars().all())
