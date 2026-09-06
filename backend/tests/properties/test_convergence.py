"""Property: empirical (Monte Carlo) metrics converge to the parametric ones as
n_simulations -> inf. Both routes share one normalizer, so this is a statement
about sampling error, not about differing conventions."""

from __future__ import annotations

import numpy as np
import pytest

from app.contracts.comparison import ModelId
from app.engines.common.normalize import (
    metrics_from_moments,
    metrics_from_paths,
    portfolio_moments,
)
from app.engines.monte_carlo import simulate_chunk
from tests.conftest import collect, context_for, make_request


def test_normalizer_paths_converge_to_moments():
    """Directly: simulate GBM terminal values for a known (mu, sigma) and check
    the empirical normalizer approaches the parametric one at large n."""
    mu, sigma = 0.08, 0.18
    horizon, V0, conf, rf = 10.0, 100_000.0, 0.95, 0.04

    parametric = metrics_from_moments(mu, sigma, horizon, conf, V0, rf)
    terminal, _ = simulate_chunk(
        mu, sigma, horizon, n_steps=120,
        n_paths=400_000, initial_value=V0, seed=7,
    )
    empirical = metrics_from_paths(terminal, horizon, conf, V0, rf)

    assert empirical["expected_return"] == pytest.approx(
        parametric["expected_return"], abs=2e-3
    )
    assert empirical["volatility"] == pytest.approx(
        parametric["volatility"], abs=2e-3
    )
    assert empirical["prob_loss"] == pytest.approx(
        parametric["prob_loss"], abs=5e-3
    )
    assert empirical["var_horizon"] == pytest.approx(
        parametric["var_horizon"], rel=2e-2
    )


async def test_mc_engine_converges_to_parametric_baseline(bundle, sectors):
    """The Monte Carlo engine's complete outcome converges to the parametric
    normal metrics computed from the same historical portfolio moments."""
    from app.engines import build_registry

    req = make_request([ModelId.MONTE_CARLO], sectors, n_sims=200_000)
    ctx = context_for(req, bundle)
    engine = build_registry()[ModelId.MONTE_CARLO]

    transitions = await collect(engine, ctx)
    final = [t for t in transitions if t.is_terminal][0]
    assert final.outcome is not None
    mc = final.outcome.metrics

    mu_p, sigma_p = portfolio_moments(
        ctx.weights,
        bundle.artifacts.sector_mu_annual,
        bundle.artifacts.sector_cov_annual,
    )
    baseline = metrics_from_moments(
        mu_p, sigma_p, ctx.horizon_years, ctx.confidence, ctx.initial_value,
        bundle.artifacts.risk_free_annual,
    )
    assert mc.expected_return == pytest.approx(baseline["expected_return"], abs=3e-3)
    assert mc.volatility == pytest.approx(baseline["volatility"], abs=3e-3)
    assert mc.prob_loss == pytest.approx(baseline["prob_loss"], abs=1e-2)
