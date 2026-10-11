"""
The prompt. Versioned, because the narration cache key embeds PROMPT_VERSION —
bumping it is what makes editing this file safe.

The whole prompt is rendered from a NarrationPayload and nothing else, so the
privacy guarantee in payload.py is not weakened by some other value being
interpolated here.
"""

from __future__ import annotations

from .payload import NarrationPayload

PROMPT_VERSION = "n1"

SYSTEM_PROMPT = """\
You write one short explanation for each suggested sector shift in an \
educational investing tool. The shifts, and every number attached to them, \
have already been computed by a risk model. You are not choosing, ranking or \
evaluating them — you are explaining, in plain language, what the model's own \
figures say about each one.

Rules, all of them strict:

1. Use ONLY the figures given to you, copied exactly as written. Never \
calculate a new number, never round differently, never approximate, and never \
write a number as a word ("fifteen percent"). If a figure you want is not in \
the input, leave it out.
2. Name ONLY the sectors that appear in the input. Never mention a company, a \
ticker symbol, or a fund.
3. Never tell the reader to buy, sell, hold, trade, purchase or rebalance \
anything, and never say they "should" do something. This is a lens on a model, \
not advice. Describe what the model's numbers say, not what the reader ought \
to do.
4. Never promise or guarantee an outcome — these are estimates from a model, \
not forecasts. Write about what the figures show, not about what the future \
holds: avoid "will", "should", "ensures" and "guarantees", and prefer the \
present tense ("volatility falls from X to Y") over the predictive one.
5. Return exactly one entry per move, in the order given, echoing each move's \
from_sector and to_sector unchanged.

Style: one or two sentences per move, plain and concrete, no jargon beyond what \
the input uses, no preamble and no sign-off. Lead with whatever the risk level \
ranks by — volatility reduction for conservative, return per unit of risk for \
moderate, expected return for aggressive — and always mention the other side of \
the trade-off, so no explanation hides a cost. Vary the sentence shape between \
moves; do not use the same template three times.

Call the Sharpe ratio "return per unit of risk"."""


def user_message(payload: NarrationPayload) -> str:
    """The entire request body, built from the payload alone."""
    note = ""
    if "parametric_estimate" in payload.warnings:
        note = (
            "\n\nNote: this model scored these shifts in closed form from the "
            "same inputs it simulates, rather than re-simulating each one. You "
            "may call the figures estimates, but do not add any caveat beyond "
            "that."
        )
    return (
        f"Model: {payload.model_display_name}\n"
        f"Risk level the shifts were ranked at: {payload.risk_level}\n"
        f"Estimation method: {payload.estimation_method}\n\n"
        f"The portfolio's current sector weights:\n"
        f"{_weights(payload)}\n\n"
        f"The moves to explain, already ranked, best first:\n"
        f"{_moves(payload)}"
        f"{note}"
    )


def _weights(payload: NarrationPayload) -> str:
    return "\n".join(f"  {s}: {w}" for s, w in payload.current_weights.items())


def _moves(payload: NarrationPayload) -> str:
    blocks = []
    for i, m in enumerate(payload.moves, start=1):
        blocks.append(
            f"{i}. Shift {m.move_pct} of the portfolio "
            f"from {m.from_sector} to {m.to_sector}\n"
            f"     return per unit of risk: {m.sharpe_before} -> "
            f"{m.sharpe_after} (change {m.sharpe_delta})\n"
            f"     volatility: {m.vol_before_pct} -> {m.vol_after_pct} "
            f"(change {m.vol_delta_pts} percentage points)\n"
            f"     expected return: {m.return_before_pct} -> "
            f"{m.return_after_pct} (change {m.return_delta_pts} "
            f"percentage points)"
        )
    return "\n".join(blocks)
