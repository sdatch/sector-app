"""Properties of suggested sector shifts: every shift is a legal, long-only,
sum-preserving tilt that strictly improves Sharpe within its risk level; and a
parametric engine's `metrics_after` is exactly what that engine reports when the
shifted weights are actually held (normalize is the only producer)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts.comparison import (
    Allocation,
    EstimationMethod,
    ModelId,
    RiskLevel,
    SectorWeight,
)
from app.engines.common.shifts import AGGRESSIVE_VOL_CAP, suggest_shifts
from tests.conftest import collect, context_for, make_request


def _apply(w: np.ndarray, sectors, shift) -> np.ndarray:
    idx = {s: i for i, s in enumerate(sectors)}
    out = w.copy()
    out[idx[shift.from_sector]] = max(out[idx[shift.from_sector]] - shift.fraction, 0.0)
    out[idx[shift.to_sector]] += shift.fraction
    return out


@settings(max_examples=150, deadline=None)
@given(
    raw_w=st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=2, max_size=8),
    seed=st.integers(min_value=0, max_value=2**31),
    level=st.sampled_from(list(RiskLevel)),
)
def test_shifts_are_legal_and_improve(raw_w, seed, level):
    w = np.array(raw_w)
    if w.sum() == 0:
        return
    w = w / w.sum()
    S = len(w)
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(S, S))
    cov = A @ A.T / S * 0.04 + np.eye(S) * 0.01
    mu = rng.normal(0.07, 0.04, size=S)
    sectors = tuple(f"S{i}" for i in range(S))

    shifts = suggest_shifts(
        w, mu, cov, sectors, level, 10.0, 0.95, 100_000.0, 0.03,
        EstimationMethod.PARAMETRIC_NORMAL,
    )
    assert len(shifts) <= 3
    pairs = [(s.from_sector, s.to_sector) for s in shifts]
    assert len(set(pairs)) == len(pairs)
    for s in shifts:
        assert s.from_sector != s.to_sector
        assert s.fraction <= w[sectors.index(s.from_sector)] + 1e-12
        shifted = _apply(w, sectors, s)
        assert (shifted >= 0).all()
        assert shifted.sum() == pytest.approx(1.0, abs=1e-9)
        b, a = s.metrics_before, s.metrics_after
        assert a.sharpe_ratio > b.sharpe_ratio
        if level is RiskLevel.CONSERVATIVE:
            assert a.volatility < b.volatility
        elif level is RiskLevel.MODERATE:
            assert a.volatility <= b.volatility + 1e-9
        else:
            assert a.volatility <= AGGRESSIVE_VOL_CAP * b.volatility + 1e-9


def test_single_sector_portfolio_only_moves_out():
    sectors = ("A", "B", "C")
    w = np.array([1.0, 0.0, 0.0])
    cov = np.diag([0.09, 0.02, 0.03])
    mu = np.array([0.06, 0.07, 0.08])
    shifts = suggest_shifts(
        w, mu, cov, sectors, RiskLevel.MODERATE, 5.0, 0.95, 1.0, 0.02,
        EstimationMethod.PARAMETRIC_NORMAL,
    )
    assert shifts
    assert all(s.from_sector == "A" for s in shifts)


@pytest.mark.parametrize("model_id", [ModelId.FAMA_FRENCH, ModelId.BLACK_LITTERMAN])
@pytest.mark.parametrize("level", list(RiskLevel))
async def test_metrics_after_reproduce_engine(bundle, sectors, model_id, level):
    from app.engines import build_registry

    engine = build_registry()[model_id]
    req = make_request([model_id], sectors).model_copy(update={"risk_level": level})
    ctx = context_for(req, bundle)
    outcome = [t for t in await collect(engine, ctx) if t.is_terminal][0].outcome
    assert outcome.suggested_shifts, f"{model_id}/{level}: expected shifts"
    for s in outcome.suggested_shifts:
        assert s.metrics_before == outcome.metrics
        shifted = _apply(ctx.weights, sectors, s)
        alloc = Allocation(
            sector_weights=[
                SectorWeight(sector=sec, weight=float(shifted[i]))
                for i, sec in enumerate(sectors)
                if shifted[i] > 0
            ]
        )
        req2 = req.model_copy(update={"allocation": alloc})
        o2 = [
            t for t in await collect(engine, context_for(req2, bundle)) if t.is_terminal
        ][0].outcome
        for field, v in s.metrics_after.model_dump().items():
            assert getattr(o2.metrics, field) == pytest.approx(v, rel=1e-9, abs=1e-9), field


async def test_monte_carlo_shifts_are_labeled_parametric(bundle, sectors):
    from app.engines import build_registry

    engine = build_registry()[ModelId.MONTE_CARLO]
    req = make_request([ModelId.MONTE_CARLO], sectors, n_sims=3_000)
    transitions = await collect(engine, context_for(req, bundle))
    with_outcome = [t.outcome for t in transitions if t.outcome is not None]
    assert len(with_outcome) >= 2  # provisional + final
    first = with_outcome[0].suggested_shifts
    assert first and all(o.suggested_shifts == first for o in with_outcome)
    for s in first:
        assert s.estimation_method is EstimationMethod.PARAMETRIC_NORMAL
        assert "parametric_estimate" in s.warnings
