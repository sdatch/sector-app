"""
The honesty boundary: what a reply must satisfy before anyone sees it.

Unlike narration, entries are independent — one confused symbol says nothing
about the others — so a bad entry is dropped on its own rather than rejecting
the batch. A dropped symbol is reported as not checked, never as "unknown",
because "the model could not identify this" and "the model said something we
refused to show" are different statements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.portfolios.sectors import SECTOR_CODE

from .payload import LookupPayload, normalize_symbol
from .schema import LookupOutput, TickerClassification

log = logging.getLogger(__name__)

_MAX_RATIONALE = 300
_MAX_NAME = 120


@dataclass(frozen=True)
class SectorSuggestion:
    ticker: str
    company_name: str | None
    kind: str
    sector: str | None
    confidence: str
    rationale: str
    searched: bool


def _reason(c: TickerClassification) -> str | None:
    if c.kind == "stock":
        if c.sector is None:
            return "stock_without_sector"
        if c.sector not in SECTOR_CODE:
            return "foreign_sector"
    elif c.sector is not None:
        return "sector_on_non_stock"
    if not c.rationale.strip():
        return "empty_rationale"
    return None


def validate_output(
    parsed: LookupOutput | None, payload: LookupPayload
) -> dict[str, SectorSuggestion]:
    """ticker -> suggestion, for every entry that passed. Absent = not checked."""
    if parsed is None:
        return {}
    wanted = set(payload.tickers)
    out: dict[str, SectorSuggestion] = {}
    for c in parsed.classifications:
        ticker = normalize_symbol(c.ticker)
        if ticker not in wanted:
            log.warning("sector lookup rejected: unrequested_ticker")
            continue
        if ticker in out:
            # Two answers for one symbol: trust neither.
            log.warning("sector lookup rejected: duplicate_ticker")
            out.pop(ticker)
            wanted.discard(ticker)
            continue
        reason = _reason(c)
        if reason is not None:
            log.warning("sector lookup rejected: %s", reason)
            continue
        out[ticker] = SectorSuggestion(
            ticker=ticker,
            company_name=(c.company_name or "").strip()[:_MAX_NAME] or None,
            kind=c.kind,
            sector=c.sector,
            confidence=c.confidence,
            rationale=c.rationale.strip()[:_MAX_RATIONALE],
            searched=c.searched,
        )
    return out
