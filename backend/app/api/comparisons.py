"""
Comparison resource + SSE routers (endpoint spec §2–8).

All routes require an authenticated user; POST is hard-gated on email
verification (user_model_spec §1.1 — 403 for unverified). Comparisons are
user-scoped: a user can only read/cancel their own. A portfolio_id allocation
is resolved to sector weights against the current snapshot before evaluation,
and the resolved weights (not the id) enter the cache key so an edited portfolio
never hits a stale entry (user_model_spec §3.4).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.csrf import require_csrf_header
from app.auth.users import current_active_user, current_verified_user
from app.contracts.comparison import (
    Allocation,
    ComparisonResource,
    ComparisonStatus,
    CompareRequest,
    ModelId,
    SectorWeight,
)
from app.db.base import get_async_session
from app.db.models import User
from app.engines.context import AllocationError
from app.history.service import get_comparison_row, list_comparisons
from app.orchestration.events import Event
from app.portfolios.service import get_portfolio, resolve_allocation

router = APIRouter(prefix="/v1", tags=["comparisons"])


class ComparisonSummary(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    portfolio_id: uuid.UUID | None
    snapshot_id: str
    models: list[ModelId]


async def _resolve_portfolio_allocation(
    body: CompareRequest, request: Request, user: User, session: AsyncSession
) -> tuple[CompareRequest, str | None]:
    """If the allocation is a portfolio_id, load the user's portfolio and
    rewrite the request to explicit sector weights. Returns (request, pid)."""
    pid = body.allocation.portfolio_id
    if pid is None:
        return body, None

    portfolio = await get_portfolio(session, user.id, pid)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="portfolio_not_found")

    bundle = request.app.state.snapshots.get(
        request.app.state.settings.active_snapshot_id
    )
    resolved_alloc = resolve_allocation(
        portfolio, bundle.ticker_price, bundle.fund_composition
    )
    if not resolved_alloc:
        raise HTTPException(status_code=422, detail="portfolio_not_priceable")

    sector_weights = [
        SectorWeight(sector=s, weight=w) for s, w in resolved_alloc.weights.items()
    ]
    resolved = body.model_copy(
        update={"allocation": Allocation(sector_weights=sector_weights)}
    )
    return resolved, str(portfolio.id)


@router.post("/comparisons", response_model=ComparisonResource)
async def create_comparison(
    body: CompareRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_verified_user),
    session: AsyncSession = Depends(get_async_session),
    _: None = Depends(require_csrf_header),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ComparisonResource:
    app = request.app
    manager = app.state.manager
    idem = app.state.idempotency
    limiter = app.state.limiter

    if idempotency_key:
        existing = idem.get(idempotency_key)
        if existing and manager.owns(existing, str(user.id)):
            resource = manager.get_resource(existing)
            if resource is not None:
                response.status_code = 200
                return resource

    body, portfolio_id = await _resolve_portfolio_allocation(
        body, request, user, session
    )

    cached = manager.cache_lookup(body)
    if cached is not None:  # cache hits are exempt from rate limiting (§8)
        response.status_code = 200
        response.headers["X-Cache"] = "hit"
        return cached

    allowed, retry_after = limiter.check(
        str(user.id), asyncio.get_running_loop().time()
    )
    if not allowed:
        raise HTTPException(
            status_code=429, detail="rate_limited",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    try:
        resource, cache_hit = await manager.create(
            body, user_id=str(user.id), portfolio_id=portfolio_id
        )
    except AllocationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if cache_hit:
        response.status_code = 200
        response.headers["X-Cache"] = "hit"
    else:
        response.status_code = 201
        response.headers["Location"] = f"/v1/comparisons/{resource.id}"
        if idempotency_key:
            idem.put(idempotency_key, str(resource.id))
    return resource


def _require_owned(manager, comparison_id: str, user: User) -> ComparisonResource:
    resource = manager.get_resource(comparison_id)
    if resource is None or not manager.owns(comparison_id, str(user.id)):
        # 404 (not 403) so existence of others' comparisons isn't leaked.
        raise HTTPException(status_code=404, detail="comparison_not_found")
    return resource


@router.get("/comparisons", response_model=list[ComparisonSummary])
async def list_history(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ComparisonSummary]:
    """Past comparisons from the last 90 days (PRD FR-6 / U8)."""
    now = datetime.now(timezone.utc)
    rows = await list_comparisons(session, user.id, now)
    return [
        ComparisonSummary(
            id=r.id,
            status=r.status,
            created_at=r.created_at,
            portfolio_id=r.portfolio_id,
            snapshot_id=r.snapshot_id,
            models=r.request.get("models", []),
        )
        for r in rows
    ]


@router.get("/comparisons/{comparison_id}", response_model=ComparisonResource)
async def get_comparison(
    comparison_id: str,
    request: Request,
    response: Response,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> ComparisonResource:
    manager = request.app.state.manager
    # Live in-memory state first (may still be running).
    if manager.get_resource(comparison_id) is not None:
        resource = _require_owned(manager, comparison_id, user)
        if resource.status is ComparisonStatus.RUNNING:
            response.headers["Retry-After"] = "1"
        return resource

    # Fall back to the durable store so old comparisons reopen (U8).
    try:
        cid = uuid.UUID(comparison_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="comparison_not_found")
    row = await get_comparison_row(
        session, user.id, cid, datetime.now(timezone.utc)
    )
    if row is None or row.result is None:
        raise HTTPException(status_code=404, detail="comparison_not_found")
    return ComparisonResource.model_validate(row.result)


@router.get("/comparisons/{comparison_id}/events")
async def comparison_events(
    comparison_id: str,
    request: Request,
    user: User = Depends(current_active_user),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    manager = request.app.state.manager
    _require_owned(manager, comparison_id, user)

    try:
        since = int(last_event_id) if last_event_id else 0
    except ValueError:
        since = 0

    async def event_gen():
        channel = manager.channel(comparison_id)
        if channel is None:
            resource = manager.get_resource(comparison_id)
            yield Event(
                id=1, type="comparison", data={"status": resource.status.value}
            ).to_sse()
            return

        q, backlog = channel.subscribe(since)
        try:
            for event in backlog:
                yield event.to_sse()
                if event.type == "comparison":
                    return
            while True:
                if channel.closed and q.empty():
                    return
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield event.to_sse()
                    if event.type == "comparison":
                        return
                except (asyncio.TimeoutError, TimeoutError):
                    yield Event(id=0, type="heartbeat", data={}).to_sse()
        finally:
            channel.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/comparisons/{comparison_id}", status_code=202)
async def cancel_comparison(
    comparison_id: str,
    request: Request,
    user: User = Depends(current_active_user),
    _: None = Depends(require_csrf_header),
) -> dict:
    manager = request.app.state.manager
    _require_owned(manager, comparison_id, user)
    cancelled = await manager.cancel(comparison_id)
    return {"cancelled": cancelled}
