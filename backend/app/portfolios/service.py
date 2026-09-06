"""Portfolio persistence + allocation resolution. Positions store quantity, not
weights — weights are derived at evaluation time from snapshot prices, so a
portfolio's sector mix drifts with the market exactly as it does in reality
(user_model_spec §2.2)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Portfolio, Position
from app.snapshots.providers.funds import FundComposition
from .schemas import PortfolioCreate
from .sectors import FUND_SECTOR, SECTOR_CODE


class PortfolioConflict(Exception):
    """Duplicate (user, name)."""


class PortfolioValidationError(ValueError):
    """Bad sector/ticker in a create request."""


async def _user_has_portfolios(session: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(Portfolio.id).where(Portfolio.user_id == user_id).limit(1)
    )
    return result.first() is not None


async def create_portfolio(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: PortfolioCreate,
    ticker_sector: dict[str, str],
    allowed_sectors: set[str],
    fund_composition: dict[str, FundComposition] | None = None,
) -> Portfolio:
    funds = fund_composition or {}
    if payload.accepted:
        source = "csv"
        positions = []
        for row in payload.accepted:
            sector = ticker_sector.get(row.ticker)
            if sector is None:
                comp = funds.get(row.ticker)
                if comp is None or not comp.modelable:
                    raise PortfolioValidationError(
                        f"Unknown ticker '{row.ticker}'"
                    )
                # Funds carry the sentinel; the breakdown is applied at
                # evaluation time from the snapshot, not frozen at commit.
                sector = FUND_SECTOR
            positions.append(
                Position(ticker=row.ticker, quantity=row.quantity, sector=sector)
            )
    else:
        source = "manual"
        positions = []
        for sw in payload.sector_weights:
            if sw.sector not in allowed_sectors:
                raise PortfolioValidationError(f"Unknown sector '{sw.sector}'")
            positions.append(
                Position(
                    ticker=SECTOR_CODE[sw.sector],
                    quantity=sw.weight,
                    sector=sw.sector,
                )
            )

    # First portfolio becomes the default; explicit is_default unsets others.
    make_default = payload.is_default or not await _user_has_portfolios(
        session, user_id
    )
    if make_default:
        await session.execute(
            update(Portfolio)
            .where(Portfolio.user_id == user_id, Portfolio.is_default.is_(True))
            .values(is_default=False)
        )

    portfolio = Portfolio(
        id=uuid.uuid4(),
        user_id=user_id,
        name=payload.name,
        source=source,
        is_default=make_default,
        positions=positions,
    )
    session.add(portfolio)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise PortfolioConflict() from exc
    await session.refresh(portfolio)
    return portfolio


async def list_portfolios(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Portfolio]:
    result = await session.execute(
        select(Portfolio)
        .where(Portfolio.user_id == user_id)
        .order_by(Portfolio.created_at)
    )
    return list(result.scalars().all())


async def get_portfolio(
    session: AsyncSession, user_id: uuid.UUID, portfolio_id: uuid.UUID
) -> Portfolio | None:
    result = await session.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id, Portfolio.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def delete_portfolio(
    session: AsyncSession, user_id: uuid.UUID, portfolio_id: uuid.UUID
) -> bool:
    portfolio = await get_portfolio(session, user_id, portfolio_id)
    if portfolio is None:
        return False
    await session.delete(portfolio)
    await session.commit()
    return True


@dataclass(frozen=True)
class ResolvedAllocation:
    """A portfolio resolved against a snapshot.

    `weights` always sums to 1.0 over the modelable equity sleeve — that is
    what the engines require. `unmodeled_share` is the fraction of the
    portfolio's *value* that sleeve leaves out (the fixed-income side of a
    balanced fund, say), carried alongside rather than folded in, so the UI can
    say plainly that a 60/40 portfolio is being modeled as its 60.
    """

    weights: dict[str, float]
    unmodeled_share: float = 0.0
    approximations: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.weights)


def resolve_allocation(
    portfolio: Portfolio,
    ticker_price: dict[str, float],
    fund_composition: dict[str, FundComposition] | None = None,
) -> ResolvedAllocation:
    """Resolve a portfolio to sector weights against current snapshot prices.

    Manual portfolios store weights directly as position quantities. CSV
    portfolios are valued at snapshot prices, and a position whose ticker names
    a pooled vehicle is *decomposed* across the sectors that fund actually
    holds — a fund is not a sector, and the alternative (dropping it) makes the
    tool useless for the index-fund portfolios most people hold.

    Decomposition happens here, at evaluation time, rather than at commit time,
    so refreshed fund holdings flow through to existing portfolios exactly the
    way refreshed prices already do.
    """
    funds = fund_composition or {}
    agg: dict[str, float] = defaultdict(float)
    unmodeled_value = 0.0
    notes: dict[str, None] = {}  # ordered set

    if portfolio.source == "manual":
        for p in portfolio.positions:
            agg[p.sector] += float(p.quantity)
    else:
        for p in portfolio.positions:
            value = float(p.quantity) * ticker_price.get(p.ticker, 0.0)
            if value <= 0:
                continue
            comp = funds.get(p.ticker)
            if comp is None:
                if p.sector == FUND_SECTOR:
                    # Committed as a fund, but this snapshot has no breakdown
                    # for it. Counting it as one sector would be a lie; count
                    # it as value we cannot model.
                    unmodeled_value += value
                    continue
                agg[p.sector] += value
                continue

            equity_value = value * comp.equity_share
            unmodeled_value += value - equity_value
            for sector, share in comp.sector_weights.items():
                agg[sector] += equity_value * share
            if comp.approximation:
                notes[comp.approximation] = None

    modeled = sum(agg.values())
    if modeled <= 0:
        return ResolvedAllocation({}, 1.0 if unmodeled_value > 0 else 0.0)

    total = modeled + unmodeled_value
    return ResolvedAllocation(
        weights={s: v / modeled for s, v in agg.items() if v > 0},
        unmodeled_share=(unmodeled_value / total) if total > 0 else 0.0,
        approximations=tuple(notes),
    )


def portfolio_sector_weights(
    portfolio: Portfolio,
    ticker_price: dict[str, float],
    fund_composition: dict[str, FundComposition] | None = None,
) -> dict[str, float]:
    """Weights-only view of `resolve_allocation`, for callers that do not need
    the unmodeled sleeve."""
    return resolve_allocation(portfolio, ticker_price, fund_composition).weights
