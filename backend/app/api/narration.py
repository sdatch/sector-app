"""
Narration endpoint — optional plain-language wording for a model's suggested
shifts. Off by default (config.narration_enabled).

Deliberately a separate request, made after the comparison has been returned
and painted: narration must never sit inside the 500 ms comparison budget, and
the page is complete without it.

Status-code rule: 404 (not yours, or not there), 409 (not ready), 429 (slow
down). Everything else is 200, possibly with an empty `moves` list meaning
"client, render your own copy". A client should never need to handle a
narration failure — a flag-off backend returns exactly the shape a failed
generation does.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.comparisons import load_owned_comparison
from app.auth.csrf import require_csrf_header
from app.auth.users import current_active_user
from app.contracts.comparison import ModelId, OutcomeStatus, RiskLevel
from app.db.base import get_async_session
from app.db.models import User
from app.narration import get_client, narrate

router = APIRouter(prefix="/v1", tags=["narration"])


class NarrationRequest(BaseModel):
    model_id: ModelId


class NarratedMoveRead(BaseModel):
    from_sector: str
    to_sector: str
    text: str


class NarrationResponse(BaseModel):
    model_id: ModelId
    source: str  # "claude" | "template"
    moves: list[NarratedMoveRead] = []
    prompt_version: str | None = None


def _template(model_id: ModelId) -> NarrationResponse:
    return NarrationResponse(model_id=model_id, source="template")


@router.post("/comparisons/{comparison_id}/narration")
async def narrate_comparison(
    comparison_id: str,
    body: NarrationRequest,
    request: Request,
    response: Response,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    _: None = Depends(require_csrf_header),
) -> NarrationResponse:
    app = request.app
    settings = app.state.settings

    # Flag off: answer before touching the database or the rate limiter, and in
    # the same shape as every other outcome, so the client needs no branch.
    # Consequence, accepted: with the feature off an unknown or foreign
    # comparison id also gets this 200 rather than a 404. Nothing is leaked —
    # the reply is identical for every id — and a disabled feature doing zero
    # database work is worth more than status parity across configurations.
    if not settings.narration_enabled:
        return _template(body.model_id)

    resource, cache_key = await load_owned_comparison(
        comparison_id, request, user, session
    )

    envelope = next(
        (o for o in resource.outcomes if o.model_id == body.model_id), None
    )
    if envelope is None:
        raise HTTPException(status_code=404, detail="outcome_not_found")
    if envelope.status is OutcomeStatus.FAILED:
        return _template(body.model_id)  # nothing to narrate
    if envelope.outcome is None:
        # Still pending/running. Provisional is fine: Monte Carlo computes its
        # shifts once, before the first transition, and attaches the same list
        # to every one — so provisional and complete shifts are identical and
        # the cache key is safe on either.
        raise HTTPException(
            status_code=409,
            detail="comparison_running",
            headers={"Retry-After": "1"},
        )

    # Rate limit *after* the cache lookup inside narrate() would be ideal, but
    # the limiter is cheap and the cache is checked first below for hits that
    # cost nothing. Keep hits exempt, mirroring endpoint spec §8.
    engines = app.state.engines
    engine = engines.get(body.model_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="outcome_not_found")

    cache = app.state.narration_cache
    risk_level = resource.request.risk_level or RiskLevel.MODERATE
    client = get_client(app)

    if client is not None and not _cached(cache, cache_key, body.model_id, risk_level):
        limiter = app.state.narration_limiter
        allowed, retry_after = limiter.check(
            str(user.id), asyncio.get_running_loop().time()
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="rate_limited",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    bundle = app.state.snapshots.get(settings.active_snapshot_id)
    result = await narrate(
        client=client,
        outcome=envelope.outcome,
        model_id=body.model_id,
        display_name=engine.display_name,
        risk_level=risk_level,
        comparison_cache_key=cache_key,
        cache=cache,
        all_sectors=tuple(bundle.artifacts.sectors),
        timeout_s=settings.narration_timeout_s,
    )
    return NarrationResponse(
        model_id=body.model_id,
        source=result.source,
        moves=[
            NarratedMoveRead(
                from_sector=m.from_sector, to_sector=m.to_sector, text=m.text
            )
            for m in result.moves
        ],
        prompt_version=result.prompt_version,
    )


def _cached(cache, cache_key: str, model_id: ModelId, risk_level: RiskLevel) -> bool:
    from app.narration import narration_cache_key

    return cache is not None and cache.get(
        narration_cache_key(cache_key, model_id, risk_level)
    ) is not None
