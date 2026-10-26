"""
Lookup orchestration: cache -> payload -> client (batched) -> validate -> merge.

Reached only from its own endpoint, when a user clicks "check sectors" in the
CSV preview. Never from ingestion, never from a comparison: a suggestion is
input to a *person*, and only the sector that person confirms is stored. That
is what keeps NFR-2 determinism intact while the model in the loop is not
deterministic at all.

`source` is the honest label: "model" means some or all symbols were checked
(the ones in `unchecked` were not); "unavailable" means nothing was, and the
client simply shows no suggestions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from .cache import SectorLookupCache, lookup_cache_key
from .payload import LookupPayload
from .validate import SectorSuggestion, validate_output

log = logging.getLogger(__name__)

# Concurrent model calls per lookup. Each may search the web, so a handful in
# parallel keeps a 100-symbol file to roughly one call's latency without
# bursting the account's rate limit.
_MAX_PARALLEL = 4


@dataclass(frozen=True)
class LookupResult:
    source: str  # "model" | "unavailable"
    suggestions: list[SectorSuggestion] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    model: str | None = None


UNAVAILABLE = LookupResult(source="unavailable")


def cached_suggestions(
    payload: LookupPayload, cache: SectorLookupCache | None, model: str
) -> tuple[dict[str, SectorSuggestion], list[str]]:
    hits: dict[str, SectorSuggestion] = {}
    misses: list[str] = []
    for t in payload.tickers:
        hit = cache.get(lookup_cache_key(t, model)) if cache is not None else None
        if hit is not None:
            hits[t] = hit
        else:
            misses.append(t)
    return hits, misses


async def lookup_sectors(
    *,
    client,
    payload: LookupPayload,
    cache: SectorLookupCache | None,
    model: str,
    batch_size: int = 25,
    timeout_s: float = 60.0,
) -> LookupResult:
    hits, misses = cached_suggestions(payload, cache, model)
    if not misses:
        return LookupResult(
            source="model", suggestions=_ordered(payload, hits), model=model
        )
    if client is None:
        return UNAVAILABLE

    batches = [
        LookupPayload(tickers=tuple(misses[i : i + batch_size]))
        for i in range(0, len(misses), batch_size)
    ]
    gate = asyncio.Semaphore(_MAX_PARALLEL)

    async def run(batch: LookupPayload) -> dict[str, SectorSuggestion]:
        async with gate:
            try:
                async with asyncio.timeout(timeout_s + 5.0):
                    parsed = await client.classify(batch)
            except (TimeoutError, asyncio.TimeoutError):
                log.warning("sector lookup timed out after %.0fs", timeout_s + 5.0)
                return {}
            except Exception:  # noqa: BLE001 — a fake or future client may raise
                log.warning("sector lookup client raised", exc_info=True)
                return {}
        return validate_output(parsed, batch)

    found: dict[str, SectorSuggestion] = dict(hits)
    for result in await asyncio.gather(*(run(b) for b in batches)):
        for ticker, suggestion in result.items():
            found[ticker] = suggestion
            # "unknown" is not cached: it may be a transient miss that a
            # later search resolves, and it costs the user nothing to retry.
            if cache is not None and suggestion.kind != "unknown":
                cache.put(lookup_cache_key(ticker, model), suggestion)

    if not found:
        # Every call failed or was rejected, and nothing was cached.
        return UNAVAILABLE
    return LookupResult(
        source="model",
        suggestions=_ordered(payload, found),
        unchecked=[t for t in payload.tickers if t not in found],
        model=model,
    )


def _ordered(
    payload: LookupPayload, found: dict[str, SectorSuggestion]
) -> list[SectorSuggestion]:
    return [found[t] for t in payload.tickers if t in found]
