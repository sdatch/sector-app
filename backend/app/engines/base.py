"""
Engine base layer — model engines behind one interface.

Ported from docs/compute_layer_design.py. The rule this enforces: the
API/orchestration layer never contains the words "fama", "litterman", or
"monte". It consumes a uniform stream of OutcomeTransition values from any
engine. Adding model #4 means implementing the protocol, registering it, and
adding a detail variant to the contract union — nothing else changes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from app.contracts.comparison import (
    CompareRequest,
    DataSnapshot,
    ModelId,
    ModelOutcome,
    OutcomeStatus,
)

# ---------------------------------------------------------------------------
# Snapshot artifacts — built once per rotation, immutable thereafter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotArtifacts:
    """Everything precomputed at snapshot build time. Engines receive this
    read-only; nothing here depends on a user's allocation.

    Built by snapshots/builder.py from the data providers. Persisted to disk
    (npz) and memory-mapped on startup so warm-up survives process restarts.
    """

    meta: DataSnapshot
    sectors: tuple[str, ...]  # canonical sector ordering
    sector_returns: np.ndarray  # (T, S) daily log returns
    sector_cov_annual: np.ndarray  # (S, S) shrunk covariance
    sector_mu_annual: np.ndarray  # (S,) historical mean returns (arithmetic)
    market_caps: np.ndarray  # (S,) for BL equilibrium
    factor_returns: np.ndarray  # (T, F) FF factor series (daily)
    factor_names: tuple[str, ...]  # canonical factor ordering
    factor_loadings: np.ndarray  # (S, F) precomputed regressions
    factor_premia_annual: np.ndarray  # (F,)
    factor_cov_annual: np.ndarray  # (F, F)
    residual_var: np.ndarray  # (S,) idiosyncratic variance (annual)
    fit_r2: np.ndarray  # (S,) per-sector regression R^2
    risk_free_annual: float


# ---------------------------------------------------------------------------
# Evaluation context — the normalized question every engine answers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationContext:
    """One user request, resolved and validated. Ticker/portfolio-mode
    allocations are already mapped to sector weights by the orchestrator, so
    engines only ever see the sector vector."""

    request: CompareRequest
    artifacts: SnapshotArtifacts
    weights: np.ndarray  # (S,) aligned to artifacts.sectors, sums to 1
    horizon_years: float
    confidence: float
    initial_value: float
    rng_seed: int  # derived from cache key → determinism


# ---------------------------------------------------------------------------
# Transition stream — what engines emit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeTransition:
    """In-process representation of an SSE-able state change. The API layer
    maps this 1:1 onto OutcomeEnvelope / event frames."""

    model_id: ModelId
    status: OutcomeStatus
    progress_pct: float | None = None
    outcome: ModelOutcome | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status in (OutcomeStatus.COMPLETE, OutcomeStatus.FAILED)


# ---------------------------------------------------------------------------
# The engine protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class RiskModelEngine(Protocol):
    model_id: ModelId
    model_version: str

    def evaluate(
        self, ctx: EvaluationContext
    ) -> AsyncIterator[OutcomeTransition]:
        """Yield status transitions, ending with exactly one terminal
        transition (complete or failed). Must be cancellation-safe: a raised
        asyncio.CancelledError may not leak resources. CPU-bound work must be
        dispatched to the shared ProcessPoolExecutor as pure functions of
        arrays — never block the event loop, never pickle self."""
        ...


ENGINE_REGISTRY: dict[ModelId, RiskModelEngine] = {}


def register(engine: RiskModelEngine) -> None:
    ENGINE_REGISTRY[engine.model_id] = engine


def get_engine(model_id: ModelId) -> RiskModelEngine:
    return ENGINE_REGISTRY[model_id]
