"""
Shared normalization — the ONLY producer of comparable numbers.

Engines cannot disagree about sqrt-t scaling or VaR sign conventions because
they never implement them: every engine hands this module either a
(mu_annual, sigma_annual) moment pair or an array of simulated terminal
values, and gets back CommonMetrics / OutcomeDistribution built with one fixed
set of conventions.

Convention (single source of truth, so parametric and empirical converge):
  Portfolio value follows GBM with annual arithmetic drift `mu` and annual
  volatility `sigma`. Over horizon T years the terminal value is

      V = V0 * exp( (mu - 0.5 sigma^2) T  +  sigma sqrt(T) Z ),   Z ~ N(0,1)

  so  log(V/V0) ~ Normal( m = (mu - 0.5 sigma^2) T,  s = sigma sqrt(T) ).

  - expected_return : annualized drift `mu`  (E[V] = V0 e^{mu T})
  - volatility      : annualized `sigma`
  - VaR_horizon     : V0 - quantile_{1-c}(V)     (currency; signed — a gain in
                      the tail yields a negative "loss", left unclamped so the
                      empirical estimator converges to the parametric one)
  - CVaR_horizon    : V0 - E[V | V < quantile_{1-c}(V)]
  - prob_loss       : P(V < V0)

The Monte Carlo engine feeds `metrics_from_paths` terminal values simulated
under exactly this GBM, so its empirical metrics converge to the parametric
ones as n_simulations -> inf. That convergence is a property test.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from app.contracts.comparison import (
    OutcomeDistribution,
    SectorAttribution,
)

_PCTLS = (5, 25, 50, 75, 95)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _sharpe(mu: float, sigma: float, rf: float) -> float:
    return (mu - rf) / sigma if sigma > 0 else 0.0


def metrics_from_moments(
    mu_annual: float,
    sigma_annual: float,
    horizon_years: float,
    confidence: float,
    initial_value: float,
    risk_free_annual: float,
) -> dict:
    """Parametric path (Fama-French, Black-Litterman). Returns a dict of the
    CommonMetrics fields (engine attaches it alongside attribution)."""
    T = horizon_years
    V0 = initial_value
    mu, sigma = mu_annual, sigma_annual

    m = (mu - 0.5 * sigma * sigma) * T  # mean of log(V/V0)
    s = sigma * np.sqrt(T)  # std of log(V/V0)

    alpha = 1.0 - confidence
    z_alpha = norm.ppf(alpha)  # negative

    if s > 0:
        v_alpha = V0 * np.exp(m + s * z_alpha)  # (1-c) quantile of V
        var_h = V0 - v_alpha
        # E[V | V < v_alpha] for lognormal (see module docstring derivation)
        cond_mean = V0 * np.exp(m + 0.5 * s * s) * norm.cdf(z_alpha - s) / alpha
        cvar_h = V0 - cond_mean
        prob_loss = float(norm.cdf(-m / s))
    else:
        var_h = cvar_h = 0.0
        prob_loss = 1.0 if m < 0 else 0.0

    return {
        "expected_return": float(mu),
        "volatility": float(sigma),
        "sharpe_ratio": float(_sharpe(mu, sigma, risk_free_annual)),
        "var_horizon": float(var_h),
        "cvar_horizon": float(cvar_h),
        "prob_loss": float(np.clip(prob_loss, 0.0, 1.0)),
    }


def metrics_from_paths(
    terminal_values: np.ndarray,
    horizon_years: float,
    confidence: float,
    initial_value: float,
    risk_free_annual: float,
) -> dict:
    """Empirical path (Monte Carlo). Same field semantics and sign
    conventions as metrics_from_moments, by construction."""
    T = horizon_years
    V0 = initial_value
    V = np.asarray(terminal_values, dtype=np.float64)

    mean_v = float(V.mean())
    # Annualized drift such that E[V] = V0 e^{mu T}; converges to parametric mu.
    mu = np.log(mean_v / V0) / T if mean_v > 0 else 0.0
    logret = np.log(V / V0)
    sigma = float(logret.std(ddof=1)) / np.sqrt(T)

    alpha = 1.0 - confidence
    v_alpha = float(np.quantile(V, alpha))
    var_h = V0 - v_alpha
    tail = V[V <= v_alpha]
    cvar_h = V0 - float(tail.mean()) if tail.size else var_h
    prob_loss = float(np.mean(V < V0))

    return {
        "expected_return": float(mu),
        "volatility": float(sigma),
        "sharpe_ratio": float(_sharpe(mu, sigma, risk_free_annual)),
        "var_horizon": float(var_h),
        "cvar_horizon": float(cvar_h),
        "prob_loss": float(np.clip(prob_loss, 0.0, 1.0)),
    }


# ---------------------------------------------------------------------------
# Terminal-value distribution
# ---------------------------------------------------------------------------


def distribution_from_moments(
    mu_annual: float,
    sigma_annual: float,
    horizon_years: float,
    initial_value: float,
) -> OutcomeDistribution:
    T = horizon_years
    V0 = initial_value
    m = (mu_annual - 0.5 * sigma_annual**2) * T
    s = sigma_annual * np.sqrt(T)
    pct = {
        f"p{p}": float(V0 * np.exp(m + s * norm.ppf(p / 100.0)))
        for p in _PCTLS
    }
    return OutcomeDistribution(**pct)


def distribution_from_paths(
    terminal_values: np.ndarray,
) -> OutcomeDistribution:
    V = np.asarray(terminal_values, dtype=np.float64)
    qs = np.percentile(V, _PCTLS)
    return OutcomeDistribution(**{f"p{p}": float(q) for p, q in zip(_PCTLS, qs)})


# ---------------------------------------------------------------------------
# Euler sector attribution — additive across sectors for every model
# ---------------------------------------------------------------------------


def euler_attribution(
    weights: np.ndarray,
    mu_vec: np.ndarray,
    cov_annual: np.ndarray,
    sectors: tuple[str, ...],
    include_zero_weight: bool = False,
) -> list[SectorAttribution]:
    """risk_contribution_i = w_i * (cov @ w)_i / sigma_p  — sums to sigma_p.
    return_contribution_i = w_i * mu_i                    — sums to w·mu.

    Every model routes through here, so the Euler identity holds identically
    across FF, BL, and MC (MC passes the same cov it simulated from)."""
    w = np.asarray(weights, dtype=np.float64)
    mu = np.asarray(mu_vec, dtype=np.float64)
    cov = np.asarray(cov_annual, dtype=np.float64)

    port_var = float(w @ cov @ w)
    sigma_p = np.sqrt(port_var) if port_var > 0 else 0.0
    marginal = cov @ w  # (S,)

    out: list[SectorAttribution] = []
    for i, sector in enumerate(sectors):
        if not include_zero_weight and w[i] == 0.0:
            continue
        risk_contrib = (w[i] * marginal[i] / sigma_p) if sigma_p > 0 else 0.0
        out.append(
            SectorAttribution(
                sector=sector,
                weight=float(w[i]),
                return_contribution=float(w[i] * mu[i]),
                risk_contribution=float(risk_contrib),
            )
        )
    return out


def portfolio_moments(
    weights: np.ndarray,
    mu_vec: np.ndarray,
    cov_annual: np.ndarray,
) -> tuple[float, float]:
    """Portfolio annual arithmetic mean and annual volatility."""
    w = np.asarray(weights, dtype=np.float64)
    mu_p = float(w @ np.asarray(mu_vec, dtype=np.float64))
    var_p = float(w @ np.asarray(cov_annual, dtype=np.float64) @ w)
    return mu_p, float(np.sqrt(max(var_p, 0.0)))
