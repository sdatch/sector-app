"""Golden + determinism + contract-sanity tests on the frozen snapshot.

The golden file is generated on first run (SECTOR_INSIGHT_WRITE_GOLDEN=1) and
committed; thereafter the engines must reproduce it bit-for-bit. This is the
M1 exit gate: "Engines reproduce goldens on frozen snapshot."
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.contracts.comparison import ModelId
from tests.conftest import collect, context_for, make_request

GOLDEN_PATH = Path(__file__).parent / "golden_outcomes.json"
ALL_MODELS = [ModelId.FAMA_FRENCH, ModelId.BLACK_LITTERMAN, ModelId.MONTE_CARLO]


async def _terminal_outcome(model_id, bundle, sectors):
    from app.engines import build_registry

    engine = build_registry()[model_id]
    req = make_request([model_id], sectors, n_sims=8_000)
    ctx = context_for(req, bundle, seed=99)
    transitions = await collect(engine, ctx)
    terminal = [t for t in transitions if t.is_terminal]
    assert len(terminal) == 1, f"{model_id}: expected exactly one terminal"
    assert terminal[0].outcome is not None
    return terminal[0].outcome


async def _all_outcomes(bundle, sectors) -> dict:
    result = {}
    for m in ALL_MODELS:
        outcome = await _terminal_outcome(m, bundle, sectors)
        result[m.value] = outcome.model_dump(mode="json")
    return result


async def test_engines_reproduce_golden(bundle, sectors):
    current = await _all_outcomes(bundle, sectors)

    if os.environ.get("SECTOR_INSIGHT_WRITE_GOLDEN") == "1":
        GOLDEN_PATH.write_text(json.dumps(current, indent=2, sort_keys=True))
        pytest.skip("golden regenerated")

    assert GOLDEN_PATH.exists(), (
        "golden file missing; regenerate with "
        "SECTOR_INSIGHT_WRITE_GOLDEN=1 pytest tests/golden"
    )
    golden = json.loads(GOLDEN_PATH.read_text())
    assert current == golden, "engine output drifted from committed golden"


async def test_determinism_repeated_runs(bundle, sectors):
    """Identical request + snapshot + seed => identical output (NFR-2)."""
    first = await _all_outcomes(bundle, sectors)
    second = await _all_outcomes(bundle, sectors)
    assert first == second


@pytest.mark.parametrize("model_id", ALL_MODELS)
async def test_contract_sanity(model_id, bundle, sectors):
    outcome = await _terminal_outcome(model_id, bundle, sectors)
    m = outcome.metrics
    d = outcome.distribution

    assert m.volatility > 0
    assert 0.0 <= m.prob_loss <= 1.0
    assert d.p5 < d.p25 < d.p50 < d.p75 < d.p95
    # CVaR is at least as severe as VaR (expected loss beyond the quantile).
    assert m.cvar_horizon >= m.var_horizon - 1e-6
    # Attribution weights sum to ~1 over the allocated sectors.
    assert sum(a.weight for a in outcome.sector_attribution) == pytest.approx(
        1.0, abs=1e-6
    )
