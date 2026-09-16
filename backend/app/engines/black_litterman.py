"""
Black-Litterman engine. One-shot.

Equilibrium returns from market caps + sector covariance (reverse
optimization); posterior via the BL update with the user's views; posterior
moments flow through the shared normalizer. detail carries equilibrium vs
posterior returns and the optimal_weights advice delta (max-Sharpe under the
posterior). A view on an unknown sector -> terminal failed, retryable=False,
without disturbing the other engines.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import numpy as np

from app.contracts.comparison import (
    BlackLittermanDetail,
    CommonMetrics,
    Diagnostics,
    EstimationMethod,
    ModelId,
    ModelOutcome,
    OutcomeStatus,
)

from .base import EvaluationContext, OutcomeTransition
from .common.shifts import suggest_shifts
from .common.normalize import (
    distribution_from_moments,
    euler_attribution,
    metrics_from_moments,
)

_RISK_AVERSION = 2.5  # delta — reverse-optimization risk aversion
_TAU = 0.05  # uncertainty scaling on the equilibrium prior


class BlackLittermanEngine:
    model_id = ModelId.BLACK_LITTERMAN
    model_version = "bl.1"

    async def evaluate(
        self, ctx: EvaluationContext
    ) -> AsyncIterator[OutcomeTransition]:
        a = ctx.artifacts
        w = ctx.weights
        rf = a.risk_free_annual
        sectors = a.sectors
        idx = {s: i for i, s in enumerate(sectors)}
        Sigma = a.sector_cov_annual  # (S, S)
        S = len(sectors)

        # Validate views before any linear algebra — unknown sector fails fast.
        for v in ctx.request.views:
            if v.sector not in idx:
                yield OutcomeTransition(
                    model_id=self.model_id,
                    status=OutcomeStatus.FAILED,
                    error_code="unknown_sector",
                    error_message=(
                        f"Black-Litterman outcome unavailable: view references "
                        f"unknown sector '{v.sector}'"
                    ),
                    retryable=False,
                )
                return

        # Equilibrium (implied) excess returns: pi = delta * Sigma @ w_mkt.
        w_mkt = a.market_caps  # (S,), sums to 1
        pi = _RISK_AVERSION * (Sigma @ w_mkt)  # excess

        # BL posterior.
        tau_sigma = _TAU * Sigma
        views = ctx.request.views
        if views:
            K = len(views)
            P = np.zeros((K, S))
            Q = np.zeros(K)
            omega_diag = np.zeros(K)
            for k, v in enumerate(views):
                i = idx[v.sector]
                P[k, i] = 1.0
                Q[k] = v.expected_annual_return - rf  # excess view
                base = float(P[k] @ tau_sigma @ P[k])
                # Higher confidence -> smaller Omega (tighter view).
                omega_diag[k] = max(base * (1.0 / v.confidence - 1.0), 1e-12)
            Omega = np.diag(omega_diag)

            inv_tau_sigma = np.linalg.inv(tau_sigma)
            inv_omega = np.linalg.inv(Omega)
            posterior_prec = inv_tau_sigma + P.T @ inv_omega @ P
            posterior_cov = np.linalg.inv(posterior_prec)
            posterior_excess = posterior_cov @ (
                inv_tau_sigma @ pi + P.T @ inv_omega @ Q
            )
        else:
            posterior_excess = pi

        posterior_total = posterior_excess + rf  # (S,)

        # Advice delta: max-Sharpe optimal weights under the posterior.
        raw = np.linalg.solve(_RISK_AVERSION * Sigma, posterior_excess)
        long_only = np.clip(raw, 0.0, None)
        if long_only.sum() > 0:
            optimal = long_only / long_only.sum()
        else:
            optimal = w_mkt.copy()

        mu_p = float(w @ posterior_total)
        sigma_p = float(np.sqrt(max(w @ Sigma @ w, 0.0)))

        metrics = CommonMetrics(
            **metrics_from_moments(
                mu_p,
                sigma_p,
                ctx.horizon_years,
                ctx.confidence,
                ctx.initial_value,
                rf,
            )
        )
        distribution = distribution_from_moments(
            mu_p, sigma_p, ctx.horizon_years, ctx.initial_value
        )
        attribution = euler_attribution(w, posterior_total, Sigma, sectors)
        shifts = suggest_shifts(
            w, posterior_total, Sigma, sectors, ctx.request.risk_level,
            ctx.horizon_years, ctx.confidence, ctx.initial_value, rf,
            EstimationMethod.PARAMETRIC_NORMAL,
        )

        detail = BlackLittermanDetail(
            equilibrium_returns={
                s: float(pi[i] + rf) for i, s in enumerate(sectors)
            },
            posterior_returns={
                s: float(posterior_total[i]) for i, s in enumerate(sectors)
            },
            views_applied=list(views),
            optimal_weights={
                s: float(optimal[i])
                for i, s in enumerate(sectors)
                if optimal[i] > 1e-6
            },
        )
        diagnostics = Diagnostics(
            estimation_method=EstimationMethod.PARAMETRIC_NORMAL,
            data_coverage_pct=1.0,
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
        yield OutcomeTransition(
            model_id=self.model_id,
            status=OutcomeStatus.COMPLETE,
            outcome=outcome,
        )
