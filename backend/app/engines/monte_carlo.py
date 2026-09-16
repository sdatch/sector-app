"""
Monte Carlo engine. Progressive.

Stage 1: `mc_provisional_paths` paths -> provisional transition (usually inside
the sync budget). Stage 2: remaining paths in chunks -> progress transitions
(throttled by the orchestrator), then final metrics over ALL accumulated paths
-> complete. Seeded from ctx.rng_seed so identical requests produce identical
results — required for the deterministic cache contract.

Portfolio value follows GBM with the portfolio's own annual drift (w·mu) and
volatility sqrt(w'Σw), simulated with monthly steps so a genuine path exists
for max-drawdown. Terminal values feed the shared empirical normalizer, which
converges to the parametric normalizer as n_simulations -> inf (a property
test). Euler attribution passes the same Σ the paths were simulated from.

`simulate_chunk` is a module-level pure function of arrays/scalars so it can be
dispatched to the shared ProcessPoolExecutor without pickling `self`.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from app.contracts.comparison import (
    CommonMetrics,
    Diagnostics,
    EstimationMethod,
    ModelId,
    ModelOutcome,
    MonteCarloDetail,
    OutcomeStatus,
    SectorShift,
)

from .base import EvaluationContext, OutcomeTransition
from .common.shifts import suggest_shifts
from .common.normalize import (
    distribution_from_paths,
    euler_attribution,
    metrics_from_paths,
    portfolio_moments,
)


def simulate_chunk(
    mu_p: float,
    sigma_p: float,
    horizon_years: float,
    n_steps: int,
    n_paths: int,
    initial_value: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Pure GBM path simulation. Returns (terminal_values, max_drawdowns), each
    shape (n_paths,). Deterministic given seed."""
    rng = np.random.default_rng(seed)
    dt = horizon_years / n_steps
    drift = (mu_p - 0.5 * sigma_p * sigma_p) * dt
    vol = sigma_p * math.sqrt(dt)

    log_steps = rng.normal(drift, vol, size=(n_paths, n_steps))
    log_cum = np.cumsum(log_steps, axis=1)
    values = initial_value * np.exp(log_cum)  # (n_paths, n_steps)
    values = np.concatenate(
        [np.full((n_paths, 1), initial_value), values], axis=1
    )

    terminal = values[:, -1]
    running_max = np.maximum.accumulate(values, axis=1)
    drawdown = (running_max - values) / running_max
    max_dd = drawdown.max(axis=1)
    return terminal, max_dd


def _chunk_sizes(total: int, first: int, rest: int) -> list[int]:
    """First (provisional) chunk, then `rest`-sized chunks covering the
    remainder. Fixed schedule => deterministic final result."""
    if total <= first:
        return [total]
    sizes = [first]
    remaining = total - first
    while remaining > 0:
        take = min(rest, remaining)
        sizes.append(take)
        remaining -= take
    return sizes


class MonteCarloEngine:
    model_id = ModelId.MONTE_CARLO
    model_version = "mc.1"

    def __init__(
        self,
        pool: ProcessPoolExecutor | None = None,
        provisional_paths: int = 1_000,
        chunk_paths: int = 2_000,
    ) -> None:
        self._pool = pool
        self._provisional = provisional_paths
        self._chunk = chunk_paths

    async def evaluate(
        self, ctx: EvaluationContext
    ) -> AsyncIterator[OutcomeTransition]:
        import asyncio

        a = ctx.artifacts
        w = ctx.weights
        Sigma = a.sector_cov_annual
        mu_p, sigma_p = portfolio_moments(w, a.sector_mu_annual, Sigma)

        n_total = int(ctx.request.n_simulations or 10_000)
        n_steps = max(int(round(ctx.horizon_years * 12)), 1)
        sizes = _chunk_sizes(n_total, self._provisional, self._chunk)
        loop = asyncio.get_running_loop()
        # Shifts are scored in closed form from the same GBM moments the paths
        # are simulated from — re-simulating every candidate would blow the
        # first-paint budget. Labeled parametric so the UI says so.
        shifts = suggest_shifts(
            w, a.sector_mu_annual, Sigma, a.sectors, ctx.request.risk_level,
            ctx.horizon_years, ctx.confidence, ctx.initial_value,
            a.risk_free_annual, EstimationMethod.PARAMETRIC_NORMAL,
            warnings=["parametric_estimate"],
        )

        yield OutcomeTransition(
            model_id=self.model_id, status=OutcomeStatus.RUNNING, progress_pct=0.0
        )

        terminals: list[np.ndarray] = []
        drawdowns: list[np.ndarray] = []
        done = 0
        for i, size in enumerate(sizes):
            chunk_seed = (ctx.rng_seed * 1_000_003 + i) % (2**63)
            term, dd = await loop.run_in_executor(
                self._pool,
                simulate_chunk,
                mu_p,
                sigma_p,
                ctx.horizon_years,
                n_steps,
                size,
                ctx.initial_value,
                chunk_seed,
            )
            terminals.append(term)
            drawdowns.append(dd)
            done += size
            pct = done / n_total

            if i == 0 and len(sizes) > 1:
                # Provisional paint from the first chunk only.
                yield self._build_transition(
                    ctx, term, dd, mu_p, sigma_p, Sigma, shifts,
                    status=OutcomeStatus.PROVISIONAL, progress_pct=pct,
                    provisional=True,
                )
            elif i < len(sizes) - 1:
                yield OutcomeTransition(
                    model_id=self.model_id,
                    status=OutcomeStatus.RUNNING,
                    progress_pct=pct,
                )

        all_term = np.concatenate(terminals)
        all_dd = np.concatenate(drawdowns)
        yield self._build_transition(
            ctx, all_term, all_dd, mu_p, sigma_p, Sigma, shifts,
            status=OutcomeStatus.COMPLETE, progress_pct=1.0, provisional=False,
        )

    def _build_transition(
        self,
        ctx: EvaluationContext,
        terminal: np.ndarray,
        max_dd: np.ndarray,
        mu_p: float,
        sigma_p: float,
        Sigma: np.ndarray,
        shifts: list[SectorShift],
        status: OutcomeStatus,
        progress_pct: float,
        provisional: bool,
    ) -> OutcomeTransition:
        a = ctx.artifacts
        w = ctx.weights
        rf = a.risk_free_annual

        metrics = CommonMetrics(
            **metrics_from_paths(
                terminal,
                ctx.horizon_years,
                ctx.confidence,
                ctx.initial_value,
                rf,
            )
        )
        distribution = distribution_from_paths(terminal)
        attribution = euler_attribution(w, a.sector_mu_annual, Sigma, a.sectors)

        se = float(terminal.std(ddof=1) / np.sqrt(terminal.size))
        warnings = ["provisional_estimate"] if provisional else []
        diagnostics = Diagnostics(
            estimation_method=EstimationMethod.EMPIRICAL_SIMULATED,
            data_coverage_pct=1.0,
            warnings=warnings,
            convergence_std_error=se,
        )
        detail = MonteCarloDetail(
            n_simulations=int(terminal.size),
            return_model="gbm",
            max_drawdown_p50=float(np.median(max_dd)),
            prob_double=float(np.mean(terminal >= 2.0 * ctx.initial_value)),
        )
        outcome = ModelOutcome(
            model_id=self.model_id,
            model_version=self.model_version,
            metrics=metrics,
            distribution=distribution,
            sector_attribution=attribution,
            diagnostics=diagnostics,
            detail=detail,
            suggested_shifts=shifts,
        )
        return OutcomeTransition(
            model_id=self.model_id,
            status=status,
            progress_pct=progress_pct,
            outcome=outcome,
        )
