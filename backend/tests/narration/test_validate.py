"""The honesty boundary: generated prose is checked against the figures it was
given, and anything unverifiable falls back to deterministic copy.

One case per RejectReason, plus the positive controls that matter — the checks
are only useful if sound copy actually survives them.
"""

from __future__ import annotations

import pytest

from app.narration.payload import MovePayload, NarrationPayload
from app.narration.schema import NarratedMove, NarrationOutput
from app.narration.validate import RejectReason, validate_output

ALL_SECTORS = (
    "Information Technology",
    "Health Care",
    "Financials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
)

PAYLOAD = NarrationPayload(
    model_display_name="Black-Litterman",
    risk_level="moderate",
    estimation_method="parametric_normal",
    warnings=[],
    current_weights={"Energy": "31.7%", "Financials": "30.9%"},
    moves=[
        MovePayload(
            from_sector="Energy",
            to_sector="Health Care",
            move_pct="10%",
            vol_before_pct="16.30%",
            vol_after_pct="16.26%",
            vol_delta_pts="-0.04",
            return_before_pct="10.48%",
            return_after_pct="10.63%",
            return_delta_pts="+0.15",
            sharpe_before="0.379",
            sharpe_after="0.389",
            sharpe_delta="+0.010",
        )
    ],
)

GOOD = (
    "Moving 10% from Energy to Health Care lifts return per unit of risk from "
    "0.379 to 0.389, while volatility edges down from 16.30% to 16.26%."
)


def out(text: str, *, pairs=None) -> NarrationOutput:
    pairs = pairs or [("Energy", "Health Care")]
    return NarrationOutput(
        moves=[
            NarratedMove(from_sector=f, to_sector=t, text=text) for f, t in pairs
        ]
    )


def check(output) -> RejectReason | None:
    return validate_output(output, PAYLOAD, ALL_SECTORS)


# --- positive controls -----------------------------------------------------


def test_sound_copy_passes():
    assert check(out(GOOD)) is None


def test_differently_rounded_figure_passes():
    """The payload holds display strings; 16.3% and 16.30% are one claim."""
    assert check(
        out(
            "Shifting 10% from Energy to Health Care takes volatility from "
            "16.3% to 16.26% and lifts return per unit of risk to 0.389."
        )
    ) is None


def test_signed_delta_quoted_as_a_magnitude_passes():
    """We supply -0.04; prose carries the direction as a word, so the check is
    on absolute value."""
    assert check(
        out(
            "Moving 10% from Energy to Health Care trims volatility by 0.04 "
            "percentage points and lifts return per unit of risk to 0.389."
        )
    ) is None


def test_ordinals_and_small_counts_pass():
    assert check(
        out(
            "This ranks third of the three moves: return per unit of risk "
            "rises from 0.379 to 0.389 as 10% moves from Energy to Health Care."
        )
    ) is None


@pytest.mark.parametrize(
    "phrase",
    [
        "in order to lift return per unit of risk",  # "order" is not a trade
        "over the short-term the figures barely move",  # "short" is not a trade
    ],
)
def test_innocent_near_misses_pass(phrase):
    text = f"Moving 10% from Energy to Health Care, {phrase}, to 0.389."
    assert check(out(text)) is None


@pytest.mark.parametrize(
    "text",
    [
        # The shapes a language model actually reaches for. If these trip the
        # validator the layer falls back on every call and is worse than
        # useless, so they are controls, not decoration.
        "Trimming Energy by 10% in favour of Health Care nudges volatility "
        "down from 16.30% to 16.26% while lifting return per unit of risk "
        "from 0.379 to 0.389.",
        "This is the strongest risk-adjusted improvement available: 10% out "
        "of Energy and into Health Care raises return per unit of risk by "
        "0.010, and expected return edges up to 10.63%.",
        "Energy is your largest position at 31.7%; moving 10% of it to Health "
        "Care lowers volatility by 0.04 percentage points and lifts return "
        "per unit of risk to 0.389.",
        "A 10% move from Energy into Health Care barely changes volatility "
        "(16.30% to 16.26%) but improves return per unit of risk to 0.389 — "
        "the gain comes from expected return, up to 10.63%.",
    ],
)
def test_realistic_model_prose_passes(text):
    assert check(out(text)) is None


# --- rejections ------------------------------------------------------------


def test_shape_wrong_length():
    output = NarrationOutput(moves=[])
    assert check(output) is RejectReason.SHAPE_MISMATCH


def test_shape_invented_extra_move():
    output = out(GOOD, pairs=[("Energy", "Health Care"), ("Energy", "Utilities")])
    assert check(output) is RejectReason.SHAPE_MISMATCH


def test_shape_swapped_pair():
    assert check(out(GOOD, pairs=[("Health Care", "Energy")])) is \
        RejectReason.SHAPE_MISMATCH


def test_foreign_sector():
    text = GOOD + " It also reduces your exposure to Utilities."
    assert check(out(text)) is RejectReason.FOREIGN_SECTOR


@pytest.mark.parametrize("token", ["XLE", "$AAPL", "consider VTI here"])
def test_ticker_like(token):
    assert check(out(f"{GOOD} Also {token}.")) is RejectReason.TICKER_LIKE


@pytest.mark.parametrize(
    "word", ["buy", "sell", "hold", "trade", "should", "recommend", "guaranteed"]
)
def test_trade_language(word):
    assert check(out(f"You {word} this. {GOOD}")) is RejectReason.TRADE_LANGUAGE


def test_invented_number():
    text = (
        "Moving 10% from Energy to Health Care takes volatility to 9.70% and "
        "lifts return per unit of risk to 0.389."
    )
    assert check(out(text)) is RejectReason.INVENTED_NUMBER


@pytest.mark.parametrize(
    "phrase", ["roughly fifteen percent", "about a third of the portfolio"]
)
def test_number_words(phrase):
    assert check(out(f"{GOOD} It is {phrase}.")) is RejectReason.NUMBER_WORD


def test_empty_and_too_long():
    assert check(out("short")) is RejectReason.EMPTY
    assert check(out("Energy to Health Care. " * 40)) is RejectReason.TOO_LONG


def test_none_output_is_a_rejection():
    assert validate_output(None, PAYLOAD, ALL_SECTORS) is RejectReason.SHAPE_MISMATCH


def test_one_bad_move_rejects_the_whole_set():
    """The user never sees generated prose beside template prose."""
    payload = PAYLOAD.model_copy(
        update={
            "moves": [
                PAYLOAD.moves[0],
                PAYLOAD.moves[0].model_copy(update={"to_sector": "Real Estate"}),
            ]
        }
    )
    output = NarrationOutput(
        moves=[
            NarratedMove(from_sector="Energy", to_sector="Health Care", text=GOOD),
            NarratedMove(
                from_sector="Energy",
                to_sector="Real Estate",
                text="You should buy Real Estate now, it is guaranteed.",
            ),
        ]
    )
    assert validate_output(output, payload, ALL_SECTORS) is \
        RejectReason.TRADE_LANGUAGE


def test_the_dev_stub_passes_its_own_validator():
    """If the stub's output were rejected the validator would be too strict —
    this is close to the best case a real reply can look like."""
    import asyncio

    from app.narration.client import StubNarrationClient

    output = asyncio.run(StubNarrationClient().generate(PAYLOAD))
    assert validate_output(output, PAYLOAD, ALL_SECTORS) is None
