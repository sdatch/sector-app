"""
Allocation resolution + EvaluationContext construction.

The orchestrator (M2/M3) resolves a portfolio_id allocation to ticker weights
against the snapshot before calling here; this module handles the remaining
sector_weights / ticker_weights modes and produces the (S,) weight vector every
engine consumes.
"""

from __future__ import annotations

import numpy as np

from app.contracts.comparison import Allocation, CompareRequest

from .base import EvaluationContext, SnapshotArtifacts


class AllocationError(ValueError):
    """Raised when an allocation cannot be resolved against the snapshot
    universe (unknown sector or ticker). Maps to HTTP 422 in the API layer."""


def resolve_weights(
    allocation: Allocation,
    artifacts: SnapshotArtifacts,
    ticker_sector: dict[str, str] | None = None,
) -> np.ndarray:
    """Return an (S,) weight vector aligned to artifacts.sectors, summing to 1.

    portfolio_id mode must already be resolved (by the orchestrator) to one of
    the explicit modes before calling.
    """
    sectors = artifacts.sectors
    idx = {s: i for i, s in enumerate(sectors)}
    w = np.zeros(len(sectors), dtype=np.float64)

    if allocation.sector_weights:
        for sw in allocation.sector_weights:
            if sw.sector not in idx:
                raise AllocationError(f"Unknown sector '{sw.sector}'")
            w[idx[sw.sector]] += sw.weight
    elif allocation.ticker_weights:
        if ticker_sector is None:
            raise AllocationError("ticker_weights requires a ticker->sector map")
        for ticker, weight in allocation.ticker_weights.items():
            sector = ticker_sector.get(ticker)
            if sector is None or sector not in idx:
                raise AllocationError(f"Unknown ticker '{ticker}'")
            w[idx[sector]] += weight
    else:
        raise AllocationError(
            "portfolio_id must be resolved to explicit weights before "
            "resolve_weights()"
        )

    total = w.sum()
    if abs(total - 1.0) > 1e-6:
        raise AllocationError(f"Resolved weights sum to {total:.6f}, not 1.0")
    return w


def build_context(
    request: CompareRequest,
    artifacts: SnapshotArtifacts,
    rng_seed: int,
    ticker_sector: dict[str, str] | None = None,
) -> EvaluationContext:
    weights = resolve_weights(request.allocation, artifacts, ticker_sector)
    return EvaluationContext(
        request=request,
        artifacts=artifacts,
        weights=weights,
        horizon_years=request.horizon_months / 12.0,
        confidence=request.confidence_level,
        initial_value=request.initial_value,
        rng_seed=rng_seed,
    )
