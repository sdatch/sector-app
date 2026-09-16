"""
Suggested sector shifts — "what if I moved 5% from Energy to Health Care?"

One shared search every engine calls with its *own* sector moments (FF-implied,
BL posterior, historical). The candidates are identical across models; the
ranking is not, and that disagreement is the lesson.

This module adds no metric math of its own: every number on a shift comes from
normalize.portfolio_moments + normalize.metrics_from_moments, so a parametric
engine's `metrics_after` is exactly what it reports if the user actually holds
the shifted weights (a property test). `metrics_before` is the current
allocation under the same estimator, so the displayed delta is the shift alone.

Search: every held sector -> every other sector, at fixed step sizes capped at
the source weight (long-only, sum-preserving). Every qualifying shift strictly
raises Sharpe; the risk level sets the volatility cap and what is ranked first:

  conservative  volatility <  current        ranked by volatility reduction
  moderate      volatility <= current        ranked by Sharpe gain
  aggressive    volatility <= 1.10 x current ranked by expected-return gain

Ties break lexically (NFR-2 determinism); at most one shift per (from, to)
pair so the slots show three different ideas.
"""

from __future__ import annotations

import numpy as np

from app.contracts.comparison import (
    CommonMetrics,
    EstimationMethod,
    RiskLevel,
    SectorShift,
)

from .normalize import metrics_from_moments, portfolio_moments

# Volatility cap as a multiple of the current portfolio's volatility.
AGGRESSIVE_VOL_CAP = 1.10
STEP_SIZES: tuple[float, ...] = (0.05, 0.10)
MAX_SHIFTS = 3
_EPS = 1e-9


def _qualifies(level: RiskLevel, base: dict, after: dict) -> bool:
    if after["sharpe_ratio"] - base["sharpe_ratio"] <= _EPS:
        return False
    vol0, vol = base["volatility"], after["volatility"]
    if level is RiskLevel.CONSERVATIVE:
        return vol < vol0 - _EPS
    if level is RiskLevel.MODERATE:
        return vol <= vol0 + _EPS
    return vol <= AGGRESSIVE_VOL_CAP * vol0 + _EPS


def _score(level: RiskLevel, base: dict, after: dict) -> float:
    """Higher is better."""
    if level is RiskLevel.CONSERVATIVE:
        return base["volatility"] - after["volatility"]
    if level is RiskLevel.MODERATE:
        return after["sharpe_ratio"] - base["sharpe_ratio"]
    return after["expected_return"] - base["expected_return"]


def suggest_shifts(
    weights: np.ndarray,
    mu_vec: np.ndarray,
    cov_annual: np.ndarray,
    sectors: tuple[str, ...],
    risk_level: RiskLevel,
    horizon_years: float,
    confidence: float,
    initial_value: float,
    risk_free_annual: float,
    estimation_method: EstimationMethod,
    warnings: list[str] | None = None,
    k: int = MAX_SHIFTS,
) -> list[SectorShift]:
    w = np.asarray(weights, dtype=np.float64)
    mu = np.asarray(mu_vec, dtype=np.float64)
    cov = np.asarray(cov_annual, dtype=np.float64)

    def metrics(wv: np.ndarray) -> dict:
        mu_p, sigma_p = portfolio_moments(wv, mu, cov)
        return metrics_from_moments(
            mu_p, sigma_p, horizon_years, confidence, initial_value,
            risk_free_annual,
        )

    base = metrics(w)

    # (score, from, to, fraction, metrics_after)
    candidates: list[tuple[float, str, str, float, dict]] = []
    for i, src in enumerate(sectors):
        if w[i] <= _EPS:
            continue
        for frac in sorted({float(min(step, w[i])) for step in STEP_SIZES}):
            for j, dst in enumerate(sectors):
                if j == i:
                    continue
                shifted = w.copy()
                shifted[i] = max(w[i] - frac, 0.0)  # float dust at a full exit
                shifted[j] = w[j] + frac
                after = metrics(shifted)
                if _qualifies(risk_level, base, after):
                    candidates.append(
                        (_score(risk_level, base, after), src, dst, frac, after)
                    )

    candidates.sort(key=lambda c: (-c[0], c[1], c[2], c[3]))

    before = CommonMetrics(**base)
    out: list[SectorShift] = []
    used_pairs: set[tuple[str, str]] = set()
    for _, src, dst, frac, after in candidates:
        if (src, dst) in used_pairs:
            continue
        used_pairs.add((src, dst))
        out.append(
            SectorShift(
                from_sector=src,
                to_sector=dst,
                fraction=frac,
                metrics_before=before,
                metrics_after=CommonMetrics(**after),
                estimation_method=estimation_method,
                warnings=list(warnings or []),
            )
        )
        if len(out) == k:
            break
    return out
