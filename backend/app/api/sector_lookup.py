"""
Sector lookup endpoints — optional suggested sectors for the CSV preview. Off by
default (config.sector_lookup_enabled).

  GET  /v1/portfolios/sector-lookup   {available} — whether to offer the button
  POST /v1/portfolios/sector-lookup   {tickers} -> suggestions

A separate request, made only when the user clicks "check sectors": the preview
itself never waits on a model, and the page is complete without it.

Status-code rule: 422 (malformed or too many), 429 (slow down). Everything else
is 200, possibly with `source: "unavailable"` and no suggestions — the same
shape whether the flag is off, the key is missing, or the call failed, so the
client has exactly one branch.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.csrf import require_csrf_header
from app.auth.users import current_active_user
from app.db.models import User
from app.sector_lookup import (
    build_payload,
    cached_suggestions,
    get_client,
    is_symbol,
    lookup_sectors,
    normalize_symbol,
)

router = APIRouter(prefix="/v1/portfolios", tags=["sector-lookup"])


class LookupRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)


class SuggestionRead(BaseModel):
    ticker: str
    company_name: str | None = None
    kind: str  # stock | fund | non_equity | unknown
    sector: str | None = None
    confidence: str
    rationale: str
    searched: bool


class LookupResponse(BaseModel):
    source: str  # "model" | "unavailable"
    suggestions: list[SuggestionRead] = []
    # Requested but not checked: a call failed or its answer was rejected.
    unchecked: list[str] = []
    # Not ticker-shaped, so never sent anywhere.
    skipped: list[str] = []
    model: str | None = None


class AvailabilityRead(BaseModel):
    available: bool
    # Symbols one lookup accepts, so the client can trim a large file itself
    # (unknown tickers first) instead of meeting a 422.
    max_tickers: int


@router.get("/sector-lookup", response_model=AvailabilityRead)
async def availability(
    request: Request, user: User = Depends(current_active_user)
) -> AvailabilityRead:
    return AvailabilityRead(
        available=get_client(request.app) is not None,
        max_tickers=request.app.state.settings.sector_lookup_max_tickers,
    )


@router.post("/sector-lookup", response_model=LookupResponse)
async def lookup(
    body: LookupRequest,
    request: Request,
    user: User = Depends(current_active_user),
    _: None = Depends(require_csrf_header),
) -> LookupResponse:
    app = request.app
    settings = app.state.settings

    # Flag off: answer before touching the limiter, in the same shape as any
    # other outcome.
    if not settings.sector_lookup_enabled:
        return LookupResponse(source="unavailable")

    if len(body.tickers) > settings.sector_lookup_max_tickers:
        raise HTTPException(status_code=422, detail="too_many_tickers")

    symbols: list[str] = []
    skipped: list[str] = []
    for raw in body.tickers:
        t = normalize_symbol(raw)
        if is_symbol(t):
            symbols.append(t)
        else:
            skipped.append(raw)
    if not symbols:
        return LookupResponse(source="unavailable", skipped=skipped)
    payload = build_payload(symbols)

    client = get_client(app)
    cache = app.state.sector_lookup_cache
    model = settings.sector_lookup_model

    # Rate-limit only requests that would reach the model; an all-cached
    # lookup costs nothing and is exempt (mirrors endpoint spec §8).
    _, misses = cached_suggestions(payload, cache, model)
    if client is not None and misses:
        allowed, retry_after = app.state.sector_lookup_limiter.check(
            str(user.id), asyncio.get_running_loop().time()
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="rate_limited",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

    result = await lookup_sectors(
        client=client,
        payload=payload,
        cache=cache,
        model=model,
        batch_size=settings.sector_lookup_batch_size,
        timeout_s=settings.sector_lookup_timeout_s,
    )
    return LookupResponse(
        source=result.source,
        suggestions=[SuggestionRead(**s.__dict__) for s in result.suggestions],
        unchecked=result.unchecked,
        skipped=skipped,
        model=result.model,
    )
