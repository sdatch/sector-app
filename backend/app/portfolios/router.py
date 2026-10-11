"""Portfolio management + CSV ingestion routes (user_model_spec §3).

  POST /v1/portfolios/preview   multipart file -> IngestReport (nothing saved)
  POST /v1/portfolios           {name, accepted|sector_weights} -> 201 Portfolio
  GET  /v1/portfolios           list
  GET  /v1/portfolios/{id}      one
  GET  /v1/portfolios/{id}/allocation  sector mix under the active snapshot
  DELETE /v1/portfolios/{id}    remove
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf_header
from app.auth.users import current_active_user
from app.db.base import get_async_session
from app.db.models import User

from app.progress.service import store_trajectory

from app.contracts.comparison import SectorWeight

from .ingest import IngestError, parse_csv
from .schemas import (
    AllocationRead,
    IngestReport,
    PortfolioCreate,
    PortfolioRead,
)
from .service import (
    PortfolioConflict,
    PortfolioValidationError,
    create_portfolio,
    delete_portfolio,
    get_portfolio,
    list_portfolios,
    resolve_allocation,
)

router = APIRouter(prefix="/v1/portfolios", tags=["portfolios"])

_ALLOWED_MIME = {
    "text/csv",
    "text/plain",
    "application/vnd.ms-excel",
    "application/octet-stream",  # common browser/OS fallback for .csv
    "",
}


def _bundle(request: Request):
    return request.app.state.snapshots.get(
        request.app.state.settings.active_snapshot_id
    )


@router.post("/preview", response_model=IngestReport)
async def preview_upload(
    request: Request,
    file: UploadFile,
    user: User = Depends(current_active_user),
    _: None = Depends(require_csrf_header),
) -> IngestReport:
    ctype = file.content_type or ""
    if ctype not in _ALLOWED_MIME and not ctype.startswith("text/"):
        raise HTTPException(status_code=422, detail="unsupported_content_type")
    content = await file.read()
    bundle = _bundle(request)
    try:
        return parse_csv(
            content,
            bundle.ticker_sector,
            bundle.ticker_price,
            bundle.fund_composition,
        )
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=PortfolioRead, status_code=201)
async def create(
    request: Request,
    payload: PortfolioCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    _: None = Depends(require_csrf_header),
) -> PortfolioRead:
    bundle = _bundle(request)
    allowed_sectors = set(bundle.artifacts.sectors)
    try:
        portfolio = await create_portfolio(
            session,
            user.id,
            payload,
            bundle.ticker_sector,
            allowed_sectors,
            bundle.fund_composition,
        )
    except PortfolioConflict as exc:
        raise HTTPException(
            status_code=409, detail="portfolio_name_taken"
        ) from exc
    except PortfolioValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Seed the progress trajectory from snapshot history so the chart is
    # populated immediately (daily maintenance extends it thereafter).
    try:
        await store_trajectory(session, user.id, portfolio, bundle)
    except Exception:  # noqa: BLE001 — progress seeding is best-effort
        pass
    return _to_read(portfolio)


@router.get("", response_model=list[PortfolioRead])
async def list_all(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[PortfolioRead]:
    return [_to_read(p) for p in await list_portfolios(session, user.id)]


@router.get("/{portfolio_id}", response_model=PortfolioRead)
async def get_one(
    portfolio_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> PortfolioRead:
    portfolio = await get_portfolio(session, user.id, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="portfolio_not_found")
    return _to_read(portfolio)


@router.get("/{portfolio_id}/allocation", response_model=AllocationRead)
async def get_allocation(
    portfolio_id: uuid.UUID,
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> AllocationRead:
    """The portfolio's sector mix under the active snapshot, plus what the mix
    leaves out. Funds are decomposed at evaluation time, so this is a property
    of (portfolio, snapshot) rather than of any saved comparison — which is why
    it lives here and not on ComparisonResource."""
    portfolio = await get_portfolio(session, user.id, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="portfolio_not_found")
    bundle = _bundle(request)
    resolved = resolve_allocation(
        portfolio, bundle.ticker_price, bundle.fund_composition
    )
    if not resolved:
        # Same vocabulary the comparison path uses for this case.
        raise HTTPException(status_code=422, detail="portfolio_not_priceable")
    return AllocationRead(
        portfolio_id=portfolio.id,
        snapshot_id=bundle.snapshot_id,
        # Sorted so the response is deterministic for a given snapshot.
        sector_weights=[
            SectorWeight(sector=s, weight=w)
            for s, w in sorted(resolved.weights.items())
        ],
        unmodeled_share=resolved.unmodeled_share,
        approximations=list(resolved.approximations),
    )


@router.delete("/{portfolio_id}", status_code=204)
async def remove(
    portfolio_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    _: None = Depends(require_csrf_header),
) -> Response:
    deleted = await delete_portfolio(session, user.id, portfolio_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="portfolio_not_found")
    return Response(status_code=204)


def _to_read(portfolio) -> PortfolioRead:
    return PortfolioRead(
        id=portfolio.id,
        name=portfolio.name,
        source=portfolio.source,
        is_default=portfolio.is_default,
        created_at=portfolio.created_at,
        positions=[
            {"ticker": p.ticker, "quantity": float(p.quantity), "sector": p.sector}
            for p in portfolio.positions
        ],
    )
