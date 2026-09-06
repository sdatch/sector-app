"""Deterministic checks for the progressive Monte Carlo mechanism and the
rate limiter — no wall-clock timing involved."""

from __future__ import annotations

from app.contracts.comparison import ModelId, OutcomeStatus
from app.orchestration.rate_limit import SlidingWindowLimiter
from tests.conftest import collect, context_for, make_request


async def test_mc_emits_provisional_then_complete(bundle, sectors):
    from app.engines import build_registry

    req = make_request([ModelId.MONTE_CARLO], sectors, n_sims=8000)
    ctx = context_for(req, bundle)
    engine = build_registry()[ModelId.MONTE_CARLO]
    transitions = await collect(engine, ctx)

    statuses = [t.status for t in transitions]
    assert statuses[0] is OutcomeStatus.RUNNING
    assert OutcomeStatus.PROVISIONAL in statuses
    assert statuses[-1] is OutcomeStatus.COMPLETE

    provisional = next(t for t in transitions if t.status is OutcomeStatus.PROVISIONAL)
    assert "provisional_estimate" in provisional.outcome.diagnostics.warnings
    complete = transitions[-1]
    assert "provisional_estimate" not in complete.outcome.diagnostics.warnings
    # provisional uses fewer sims than the final
    assert (
        provisional.outcome.detail.n_simulations
        < complete.outcome.detail.n_simulations == 8000
    )


def test_rate_limiter_sliding_window():
    limiter = SlidingWindowLimiter(limit=3, window_s=60.0)
    for i in range(3):
        allowed, _ = limiter.check("user", now=100.0 + i)
        assert allowed
    allowed, retry = limiter.check("user", now=103.0)
    assert not allowed and retry > 0
    # after the window slides past the first hit, a slot frees up
    allowed, _ = limiter.check("user", now=161.0)
    assert allowed
