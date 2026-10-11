"""The privacy boundary (PRD NFR-3): what may leave the process, and no more.

These assert the *shape*, not a sample. A field set frozen in a test is what
turns "we were careful" into "adding a leaky field fails CI".
"""

from __future__ import annotations

import inspect
import json
import re

import pytest
from pydantic import ValidationError

from app.contracts.comparison import ModelId, RiskLevel
from app.engines import ENGINE_REGISTRY
from app.narration.payload import MovePayload, NarrationPayload, build_payload
from tests.conftest import collect, context_for, make_request

MOVE_FIELDS = {
    "from_sector",
    "to_sector",
    "move_pct",
    "vol_before_pct",
    "vol_after_pct",
    "vol_delta_pts",
    "return_before_pct",
    "return_after_pct",
    "return_delta_pts",
    "sharpe_before",
    "sharpe_after",
    "sharpe_delta",
}
PAYLOAD_FIELDS = {
    "model_display_name",
    "risk_level",
    "estimation_method",
    "warnings",
    "current_weights",
    "moves",
}


def test_field_sets_are_frozen():
    """Adding a field to either model must be a deliberate, reviewed act."""
    assert set(MovePayload.model_fields) == MOVE_FIELDS
    assert set(NarrationPayload.model_fields) == PAYLOAD_FIELDS


def test_models_forbid_extras():
    with pytest.raises(ValidationError):
        NarrationPayload(
            model_display_name="X",
            risk_level="moderate",
            estimation_method="parametric_normal",
            initial_value=100_000.0,  # the exact thing that must not travel
        )


def test_builder_cannot_see_the_things_that_must_not_leak():
    """Structural, not behavioural: the signature admits no type that carries a
    ticker, a quantity, a portfolio name or a user."""
    params = inspect.signature(build_payload).parameters
    annotations = " ".join(str(p.annotation) for p in params.values())
    for forbidden in ("ModelOutcome", "CompareRequest", "Portfolio", "User"):
        assert forbidden not in annotations


@pytest.fixture
def outcome(bundle):
    request = make_request([ModelId.BLACK_LITTERMAN], bundle.artifacts.sectors)
    engine = ENGINE_REGISTRY[ModelId.BLACK_LITTERMAN]
    ctx = context_for(request, bundle)
    import asyncio

    transitions = asyncio.run(collect(engine, ctx))
    final = transitions[-1].outcome
    assert final is not None and final.suggested_shifts
    return final


def test_serialized_payload_carries_no_identifying_data(outcome, bundle):
    payload = build_payload(
        display_name="Black-Litterman",
        risk_level=RiskLevel.MODERATE,
        estimation_method=outcome.diagnostics.estimation_method.value,
        attribution=outcome.sector_attribution,
        shifts=outcome.suggested_shifts,
    )
    blob = payload.model_dump_json()

    for ticker in bundle.ticker_price:
        assert not re.search(rf"\b{re.escape(ticker)}\b", blob), ticker
    assert "(fund)" not in blob
    assert "@" not in blob  # no email
    for money in ("100000", "100,000", "100000.0"):
        assert money not in blob
    # No uuid-shaped token (portfolio id, comparison id, user id).
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", blob)

    # And the keys really are only the allow-listed ones.
    data = json.loads(blob)
    assert set(data) == PAYLOAD_FIELDS
    for move in data["moves"]:
        assert set(move) == MOVE_FIELDS


def test_currency_metrics_are_excluded(outcome):
    """var_horizon and cvar_horizon are derived from initial_value, so they are
    not scale-free and must not travel."""
    payload = build_payload(
        display_name="Black-Litterman",
        risk_level=RiskLevel.MODERATE,
        estimation_method=outcome.diagnostics.estimation_method.value,
        attribution=outcome.sector_attribution,
        shifts=outcome.suggested_shifts,
    )
    blob = payload.model_dump_json()
    first = outcome.suggested_shifts[0]
    for value in (
        first.metrics_before.var_horizon,
        first.metrics_before.cvar_horizon,
        first.metrics_after.var_horizon,
        first.metrics_after.cvar_horizon,
    ):
        assert f"{value:.2f}" not in blob
        assert str(int(abs(value))) not in blob or abs(value) < 100


def test_unknown_warning_codes_are_dropped(outcome):
    shifts = [s.model_copy(update={"warnings": ["parametric_estimate", "x: /tmp/a"]})
              for s in outcome.suggested_shifts]
    payload = build_payload(
        display_name="Monte Carlo",
        risk_level=RiskLevel.MODERATE,
        estimation_method="parametric_normal",
        attribution=outcome.sector_attribution,
        shifts=shifts,
    )
    assert payload.warnings == ["parametric_estimate"]


def test_payload_precision_matches_what_the_ui_renders(outcome):
    """The prose quotes these strings and the client renders the delta rows
    beside them with its own formatter (frontend/lib/moves.ts `moveDigits`). If
    the two rules drift, one card shows the same quantity to two precisions.

    The rule: widen a figure whose own before/after collapses, and widen the
    risk level's ranking key when ties would hide the order.
    """
    from app.narration.payload import _digits

    shifts = outcome.suggested_shifts

    # Moderate ranks by Sharpe, so only Sharpe widens on ties.
    d = _digits(shifts, RiskLevel.MODERATE)
    assert d.sharpe in (2, 3)
    sharpes = {f"{s.metrics_after.sharpe_ratio:.2f}" for s in shifts}
    if len(sharpes) != len(shifts):
        assert d.sharpe == 3, "tied ranking key must widen"

    # Volatility is not the key here, so it widens only to show a real change.
    collapses = any(
        f"{s.metrics_before.volatility * 100:.1f}"
        == f"{s.metrics_after.volatility * 100:.1f}"
        for s in shifts
    )
    assert d.vol == (2 if collapses else 1)

    # Conservative ranks by volatility, so ties there widen it instead.
    vols = {f"{s.metrics_after.volatility * 100:.1f}" for s in shifts}
    cons = _digits(shifts, RiskLevel.CONSERVATIVE)
    if len(vols) != len(shifts) or collapses:
        assert cons.vol == 2
