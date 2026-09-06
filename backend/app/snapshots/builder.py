"""
Snapshot builder — RawMarketData -> immutable SnapshotArtifacts.

All allocation-independent, expensive work happens here, once per rotation:
covariance shrinkage, factor regressions, BL equilibrium inputs. Evaluation is
then cheap enough to honor the 500 ms budget (compute layer design, decision 3).
"""

from __future__ import annotations

import numpy as np

from app.contracts.comparison import DataSnapshot
from app.engines.base import SnapshotArtifacts

from .providers.base import RawMarketData

_TRADING_DAYS = 252


def _shrink_cov(cov: np.ndarray, delta: float = 0.10) -> np.ndarray:
    """Linear shrinkage toward the diagonal — keeps the matrix well-conditioned
    and positive-definite for BL inversion and MC sampling."""
    diag = np.diag(np.diag(cov))
    return (1.0 - delta) * cov + delta * diag


def _factor_regression(
    excess: np.ndarray, factors: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OLS of each sector's excess returns on the factors (with intercept).

    Returns (loadings (S,F), residual_daily_var (S,), r2 (S,))."""
    T, S = excess.shape
    F = factors.shape[1]
    X = np.column_stack([np.ones(T), factors])  # (T, F+1)
    # beta: (F+1, S)
    beta, *_ = np.linalg.lstsq(X, excess, rcond=None)
    loadings = beta[1:].T  # (S, F), drop intercept
    fitted = X @ beta  # (T, S)
    resid = excess - fitted
    resid_var = resid.var(axis=0, ddof=F + 1)  # (S,)
    # R^2 per sector
    ss_res = (resid**2).sum(axis=0)
    ss_tot = ((excess - excess.mean(axis=0)) ** 2).sum(axis=0)
    r2 = 1.0 - np.divide(
        ss_res, ss_tot, out=np.zeros_like(ss_res), where=ss_tot > 0
    )
    return loadings, resid_var, r2


def build_artifacts(raw: RawMarketData) -> SnapshotArtifacts:
    rf_daily = raw.risk_free_annual / _TRADING_DAYS
    # Total daily sector returns = excess + rf (rf constant => same covariance).
    total = raw.sector_excess_returns + rf_daily  # (T, S)

    sector_mu_annual = total.mean(axis=0) * _TRADING_DAYS
    sector_cov_annual = _shrink_cov(np.cov(total, rowvar=False)) * _TRADING_DAYS

    loadings, resid_daily_var, r2 = _factor_regression(
        raw.sector_excess_returns, raw.factor_returns
    )
    factor_premia_annual = raw.factor_returns.mean(axis=0) * _TRADING_DAYS
    factor_cov_annual = np.cov(raw.factor_returns, rowvar=False) * _TRADING_DAYS
    residual_var_annual = resid_daily_var * _TRADING_DAYS

    market_caps = raw.market_caps / raw.market_caps.sum()

    meta = DataSnapshot(
        snapshot_id=raw.snapshot_id,
        prices_start=raw.prices_start,
        prices_end=raw.prices_end,
        risk_free_rate_annual=raw.risk_free_annual,
        factor_data_vintage=raw.factor_data_vintage,
    )

    return SnapshotArtifacts(
        meta=meta,
        sectors=raw.sectors,
        sector_returns=np.ascontiguousarray(total),
        sector_cov_annual=np.ascontiguousarray(sector_cov_annual),
        sector_mu_annual=np.ascontiguousarray(sector_mu_annual),
        market_caps=np.ascontiguousarray(market_caps),
        factor_returns=np.ascontiguousarray(raw.factor_returns),
        factor_names=raw.factor_names,
        factor_loadings=np.ascontiguousarray(loadings),
        factor_premia_annual=np.ascontiguousarray(factor_premia_annual),
        factor_cov_annual=np.ascontiguousarray(factor_cov_annual),
        residual_var=np.ascontiguousarray(residual_var_annual),
        fit_r2=np.ascontiguousarray(r2),
        risk_free_annual=raw.risk_free_annual,
    )
