"""Property: Euler risk contributions sum to portfolio volatility, and return
contributions sum to portfolio expected return, for every engine."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts.comparison import ModelId
from app.engines.common.normalize import euler_attribution, portfolio_moments
from app.engines.context import build_context
from tests.conftest import collect, context_for, make_request


# --- Intrinsic property of the normalizer (model-agnostic) ------------------


@settings(max_examples=200, deadline=None)
@given(
    raw_w=st.lists(
        st.floats(min_value=0.0, max_value=1.0), min_size=3, max_size=8
    ),
    seed=st.integers(min_value=0, max_value=2**31),
)
def test_euler_sums_to_sigma_p(raw_w, seed):
    w = np.array(raw_w)
    if w.sum() == 0:
        return
    w = w / w.sum()
    S = len(w)
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(S, S))
    cov = A @ A.T / S + np.eye(S) * 0.05  # SPD
    mu = rng.normal(0.05, 0.1, size=S)
    sectors = tuple(f"S{i}" for i in range(S))

    attr = euler_attribution(w, mu, cov, sectors, include_zero_weight=True)
    _, sigma_p = portfolio_moments(w, mu, cov)

    risk_sum = sum(a.risk_contribution for a in attr)
    ret_sum = sum(a.return_contribution for a in attr)
    assert risk_sum == pytest.approx(sigma_p, rel=1e-9, abs=1e-12)
    assert ret_sum == pytest.approx(float(w @ mu), rel=1e-9, abs=1e-12)


# --- Same property, verified through each real engine -----------------------


@pytest.mark.parametrize(
    "model_id",
    [ModelId.FAMA_FRENCH, ModelId.BLACK_LITTERMAN, ModelId.MONTE_CARLO],
)
async def test_engine_attribution_sums(model_id, bundle, sectors):
    from app.engines import build_registry

    engine = build_registry()[model_id]
    req = make_request([model_id], sectors)
    ctx = context_for(req, bundle)
    transitions = await collect(engine, ctx)

    terminal = [t for t in transitions if t.is_terminal]
    assert len(terminal) == 1
    outcome = terminal[0].outcome
    assert outcome is not None

    risk_sum = sum(a.risk_contribution for a in outcome.sector_attribution)
    # Parametric models: attribution sigma == reported volatility exactly.
    # Monte Carlo: reported volatility is empirical, so compare to the analytic
    # portfolio sigma the attribution was built from (loose tolerance).
    if model_id is ModelId.MONTE_CARLO:
        _, sigma_p = portfolio_moments(
            ctx.weights, bundle.artifacts.sector_mu_annual,
            bundle.artifacts.sector_cov_annual,
        )
        assert risk_sum == pytest.approx(sigma_p, rel=1e-9)
    else:
        assert risk_sum == pytest.approx(outcome.metrics.volatility, rel=1e-6)
