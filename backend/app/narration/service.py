"""
Narration orchestration: cache -> payload -> client -> validate -> fallback.

This never runs inside the comparison's 500 ms budget. It is reached only by
its own endpoint, after the comparison resource has already been returned and
painted, so nothing in ComparisonManager calls into this package. Keep it that
way: narration is cosmetic and must never be able to delay a number.

`source` is the honest label for what came back. "template" means the client
should render its own deterministic copy — the backend returns no prose at all
in that case, so the wording lives in exactly one place (frontend/lib/moves.ts)
rather than being duplicated in two languages that would drift.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.contracts.comparison import ModelId, ModelOutcome, RiskLevel

from .cache import narration_cache_key
from .payload import build_payload
from .prompt import PROMPT_VERSION
from .validate import validate_output

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NarratedMoveResult:
    from_sector: str
    to_sector: str
    text: str


@dataclass(frozen=True)
class NarrationResult:
    source: str  # "claude" | "template"
    moves: list[NarratedMoveResult] = field(default_factory=list)
    prompt_version: str | None = None


TEMPLATE = NarrationResult(source="template")


async def narrate(
    *,
    client,
    outcome: ModelOutcome,
    model_id: ModelId,
    display_name: str,
    risk_level: RiskLevel,
    comparison_cache_key: str,
    cache,
    all_sectors: tuple[str, ...] = (),
    timeout_s: float = 8.0,
) -> NarrationResult:
    shifts = outcome.suggested_shifts
    if not shifts:
        # None (not computed) and [] (nothing qualified) are both "no prose to
        # write". The client already distinguishes them from the resource it
        # holds, so narration must not re-encode that distinction.
        return TEMPLATE

    key = narration_cache_key(comparison_cache_key, model_id, risk_level)
    cached = cache.get(key) if cache is not None else None
    if cached is not None:
        return NarrationResult(
            source="claude", moves=list(cached), prompt_version=PROMPT_VERSION
        )

    if client is None:
        return TEMPLATE

    payload = build_payload(
        display_name=display_name,
        risk_level=risk_level,
        estimation_method=outcome.diagnostics.estimation_method.value,
        attribution=outcome.sector_attribution,
        shifts=shifts,
    )

    try:
        async with asyncio.timeout(timeout_s + 1.0):
            parsed = await client.generate(payload)
    except (TimeoutError, asyncio.TimeoutError):
        log.warning("narration timed out after %.1fs", timeout_s + 1.0)
        return TEMPLATE
    except Exception:  # noqa: BLE001 — a fake or a future client may raise
        log.warning("narration client raised", exc_info=True)
        return TEMPLATE

    reason = validate_output(parsed, payload, all_sectors)
    if reason is not None:
        # One bad move rejects the set: the user never sees generated prose
        # beside template prose, which would look like two different voices.
        log.warning("narration rejected: %s", reason.value)
        return TEMPLATE

    moves = [
        NarratedMoveResult(
            from_sector=m.from_sector, to_sector=m.to_sector, text=m.text.strip()
        )
        for m in parsed.moves
    ]
    if cache is not None:
        cache.put(key, moves)
    return NarrationResult(
        source="claude", moves=moves, prompt_version=PROMPT_VERSION
    )
