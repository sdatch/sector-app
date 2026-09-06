"""
Compute layer design — model engines behind one interface.

The rule this file enforces: the API/orchestration layer never contains the
words "fama", "litterman", or "monte". It consumes a uniform stream of outcome
transitions from any engine. Adding model #4 means implementing the protocol,
registering it, and adding a detail variant to the contract union — nothing
else changes.

Three structural decisions:

  1. Engines are async generators of OutcomeEnvelope transitions. A one-shot
     parametric model yields once (complete). A progressive model yields
     provisional → progress → complete. The orchestrator can't tell the
     difference and doesn't want to.

  2. Comparability is enforced by construction, not convention. Every engine
     produces a raw (mu, sigma) or path array; CommonMetrics, the terminal
     distribution, and Euler sector attribution are computed by ONE shared
     normalization module. Engines cannot disagree about sqrt-t scaling or
     VaR sign conventions because they never implement them.

  3. Snapshot preparation is separated from evaluation. Expensive, allocation-
     independent work (factor regressions, covariance estimation) happens once
     per snapshot rotation and is served to engines as immutable artifacts.
     Evaluation is then cheap enough to honor the 500 ms budget.

Depends on: comparison_contract.py (v1.0)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from comparison_contract import (
    CompareRequest,
    DataSnapshot,
    ModelId,
    ModelOutcome,
)

# ---------------------------------------------------------------------------
# Snapshot artifacts — built once per rotation, immutable thereafter
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotArtifacts:
    """Everything precomputed at snapshot build time. Engines receive this
    read-only; nothing here depends on a user's allocation.

    Built by snapshots/builder.py from the data providers (price API,
    Ken French library, FRED). Persisted to disk (npz + parquet) and
    memory-mapped on startup so warm-up survives process restarts.
    """
    meta: DataSnapshot
    sectors: tuple[str, ...]                 # canonical sector ordering
    sector_returns: np.ndarray               # (T, S) daily log returns
    sector_cov_annual: np.ndarray            # (S, S) shrunk covariance
    sector_mu_annual: np.ndarray             # (S,) historical mean returns
    market_caps: np.ndarray                  # (S,) for BL equilibrium
    factor_returns: np.ndarray               # (T, F) FF factor series
    factor_loadings: np.ndarray              # (S, F) precomputed regressions
    factor_premia_annual: np.ndarray         # (F,)
    factor_cov_annual: np.ndarray            # (F, F)
    residual_var: np.ndarray                 # (S,) idiosyncratic variance
    fit_r2: np.ndarray                       # (S,) per-sector regression R^2
    risk_free_annual: float


# ---------------------------------------------------------------------------
# Evaluation context — the normalized question every engine answers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvaluationContext:
    """One user request, resolved and validated. Ticker-mode allocations are
    already mapped to sector weights by the orchestrator, so engines only
    ever see the sector vector."""
    request: CompareRequest
    artifacts: SnapshotArtifacts
    weights: np.ndarray                      # (S,) aligned to artifacts.sectors
    horizon_years: float
    confidence: float
    initial_value: float
    rng_seed: int                            # derived from cache key → determinism


# ---------------------------------------------------------------------------
# Transition stream — what engines emit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutcomeTransition:
    """In-process representation of an SSE-able state change. The API layer
    maps this 1:1 onto OutcomeEnvelope / event frames."""
    model_id: ModelId
    status: str                              # running|provisional|complete|failed
    progress_pct: float | None = None
    outcome: ModelOutcome | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False


# ---------------------------------------------------------------------------
# The engine protocol
# ---------------------------------------------------------------------------

class RiskModelEngine(Protocol):
    model_id: ModelId
    model_version: str

    async def evaluate(
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


# ---------------------------------------------------------------------------
# Shared normalization — the ONLY producer of comparable numbers
# ---------------------------------------------------------------------------
# engines/common/normalize.py — signatures shown here for the design.

def metrics_from_moments(mu_a, sigma_a, ctx):        # -> CommonMetrics
    """Parametric path: annual mean/vol -> horizon-scaled (sqrt-t) VaR/CVaR in
    currency units, Sharpe vs artifacts.risk_free_annual, P(loss) under the
    implied lognormal. Used by Fama-French and Black-Litterman."""


def metrics_from_paths(terminal_values, ctx):        # -> CommonMetrics
    """Empirical path: quantile VaR/CVaR from simulated terminal values.
    Same field semantics, same sign conventions, by construction."""


def distribution_from_moments(mu_a, sigma_a, ctx):   # -> OutcomeDistribution
def distribution_from_paths(terminal_values, ctx):   # -> OutcomeDistribution


def euler_attribution(weights, mu_vec, cov, sectors):  # -> list[SectorAttribution]
    """risk_contribution_i = w_i * (cov @ w)_i / sigma_p — additive across
    sectors for every model, because every model routes through here. The
    Monte Carlo engine passes the same cov it simulated from."""


# ---------------------------------------------------------------------------
# Engine skeletons — shape only; math lives in each module
# ---------------------------------------------------------------------------

class FamaFrenchEngine:
    """One-shot. mu from loadings @ premia + rf; cov from loadings @ factor_cov
    @ loadings.T + diag(residual_var). Portfolio moments -> shared normalize.
    Emits fit_r2 (weight-averaged) in diagnostics, loadings in detail.
    Runs inline on the event loop: pure linear algebra, ~1 ms."""
    model_id = ModelId.FAMA_FRENCH
    model_version = "ff5.1"

    async def evaluate(self, ctx):  # yields: complete
        ...


class BlackLittermanEngine:
    """One-shot. Equilibrium returns from market_caps + sector_cov (reverse
    optimization); posterior via Black-Litterman update with ctx.request.views;
    posterior moments -> shared normalize. detail carries equilibrium vs
    posterior returns and the optimal_weights advice delta (max-Sharpe under
    posterior). Unknown sector in a view -> terminal failed, retryable=False,
    without disturbing other engines."""
    model_id = ModelId.BLACK_LITTERMAN
    model_version = "bl.1"

    async def evaluate(self, ctx):  # yields: complete | failed
        ...


class MonteCarloEngine:
    """Progressive. Stage 1: 1_000 paths in-process pool -> provisional
    transition (usually inside the sync budget). Stage 2: remaining paths in
    chunks of 2_000 -> progress transitions (throttled), then final metrics
    over ALL paths -> complete. GBM under (sector_mu, sector_cov) initially;
    return_model field leaves room for block bootstrap later. Seeded from
    ctx.rng_seed so identical requests produce identical results — required
    for the deterministic cache contract."""
    model_id = ModelId.MONTE_CARLO
    model_version = "mc.1"

    def __init__(self, pool: ProcessPoolExecutor):
        self._pool = pool

    async def evaluate(self, ctx):  # yields: provisional, progress*, complete
        ...


# ---------------------------------------------------------------------------
# Orchestrator — the only consumer of engines
# ---------------------------------------------------------------------------

class Comparator:
    """Owns a comparison's lifecycle. Model-agnostic by construction.

    run() semantics:
      - resolve allocation -> EvaluationContext (once, shared)
      - launch requested engines in an asyncio.TaskGroup
      - forward every OutcomeTransition to the state store + event bus
        (in-process queues now; Redis Streams when replicas arrive)
      - gather-with-budget: return the resource snapshot at 500 ms or when
        all engines are terminal, whichever is first; remaining transitions
        continue flowing to subscribers
      - one engine's exception -> that model's terminal failed transition;
        TaskGroup does NOT cancel siblings (wrap engine tasks individually)
      - comparison terminal when every engine is terminal -> aggregate
        complete|partial|failed, emit terminal comparison event, write cache
    """

    def __init__(self, engines: dict[ModelId, RiskModelEngine], state, bus):
        ...

    async def run(self, request: CompareRequest, artifacts: SnapshotArtifacts):
        ...


# ---------------------------------------------------------------------------
# Repo layout (fresh start)
# ---------------------------------------------------------------------------
# app/
#   api/               routers, SSE framing, poll fallback
#   contracts/         comparison_contract.py (the wire schema)
#   orchestration/     Comparator, state store, event bus, cache
#   snapshots/         builder.py, artifacts.py, providers/ (prices, french, fred)
#   engines/
#     base.py          protocol, EvaluationContext, OutcomeTransition, registry
#     common/          normalize.py (sole producer of comparable numbers)
#     fama_french.py
#     black_litterman.py
#     monte_carlo.py
#   tests/
#     golden/          per-engine golden outputs on a frozen test snapshot
#     properties/      Euler contributions sum to sigma_p; parametric vs
#                      empirical metrics converge as n_simulations -> inf
