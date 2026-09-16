"""
Fama-French 5-factor engine. One-shot, pure linear algebra (a few ms incl. the shift search), runs inline
on the event loop.

mu from loadings @ premia + rf; cov from loadings @ factor_cov @ loadings.T +
diag(residual_var). Portfolio moments flow through the shared normalizer, so FF
cannot disagree with the other engines about scaling or VaR conventions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import numpy as np

from app.contracts.comparison import (
    CommonMetrics,
    Diagnostics,
    EstimationMethod,
    FamaFrenchDetail,
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


class FamaFrenchEngine:
    model_id = ModelId.FAMA_FRENCH
    model_version = "ff5.1"

    async def evaluate(
        self, ctx: EvaluationContext
    ) -> AsyncIterator[OutcomeTransition]:
        a = ctx.artifacts
        w = ctx.weights
        rf = a.risk_free_annual

        # FF-implied sector moments.
        sector_mu = rf + a.factor_loadings @ a.factor_premia_annual  # (S,)
        cov = (
            a.factor_loadings @ a.factor_cov_annual @ a.factor_loadings.T
            + np.diag(a.residual_var)
        )  # (S, S)

        mu_p = float(w @ sector_mu)
        sigma_p = float(np.sqrt(max(w @ cov @ w, 0.0)))

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
        attribution = euler_attribution(w, sector_mu, cov, a.sectors)
        shifts = suggest_shifts(
            w, sector_mu, cov, a.sectors, ctx.request.risk_level,
            ctx.horizon_years, ctx.confidence, ctx.initial_value, rf,
            EstimationMethod.PARAMETRIC_FACTOR,
        )

        port_loadings = w @ a.factor_loadings  # (F,)
        residual_vol_p = float(np.sqrt(np.sum(w**2 * a.residual_var)))
        fit_r2_p = float(w @ a.fit_r2)

        detail = FamaFrenchDetail(
            factor_loadings={
                name: float(port_loadings[i])
                for i, name in enumerate(a.factor_names)
            },
            factor_premia_annual={
                name: float(a.factor_premia_annual[i])
                for i, name in enumerate(a.factor_names)
            },
            residual_volatility=residual_vol_p,
        )
        diagnostics = Diagnostics(
            estimation_method=EstimationMethod.PARAMETRIC_FACTOR,
            data_coverage_pct=1.0,
            fit_r2=fit_r2_p,
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
