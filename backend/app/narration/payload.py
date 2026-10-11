"""
The privacy boundary (PRD NFR-3).

Everything that leaves this process for the narration model is built here, and
the shape is the enforcement: `build_payload` never takes a `ModelOutcome`, a
`CompareRequest`, a `Portfolio` or a `User`, so a ticker, a quantity, a
portfolio name, `initial_value` or a user id has no field to travel in. Both
models are `extra="forbid"` and frozen, and a test asserts their field sets, so
adding a leaky field fails CI rather than shipping quietly.

Current weights come from `SectorAttribution`, which is sector-level by
contract. They are deliberately *not* read off `CompareRequest.allocation` —
its `ticker_weights` mode carries real tickers.

Every number is pre-formatted for display at build time. That is what makes the
output validator exact instead of a float-tolerance guess: the model is given
strings to quote and has no reason to compute anything. The before/after *and*
the delta are supplied, because a model asked to work out 15.3 - 14.1 itself
would be rejected on nearly every call and the feature would always fall back.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.comparison import RiskLevel, SectorAttribution, SectorShift

# `warnings` is the one free-text channel in the shift, so it is closed to the
# codes the shift generator actually emits (engines/monte_carlo.py is the only
# caller that passes one).
_KNOWN_WARNINGS = frozenset({"parametric_estimate"})

# Metrics deliberately excluded: var_horizon and cvar_horizon are currency
# amounts derived from initial_value, and prob_loss is meaningless without the
# horizon. Only the three scale-free figures travel.


def fmt_pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def fmt_pts(x: float, digits: int = 2) -> str:
    """A change in percentage points, signed — e.g. '-1.20'."""
    return f"{x * 100:+.{digits}f}"


def fmt_num(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}"


def fmt_signed(x: float, digits: int = 3) -> str:
    return f"{x:+.{digits}f}"


class MovePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_sector: str
    to_sector: str
    move_pct: str

    vol_before_pct: str
    vol_after_pct: str
    vol_delta_pts: str

    return_before_pct: str
    return_after_pct: str
    return_delta_pts: str

    sharpe_before: str
    sharpe_after: str
    sharpe_delta: str


class NarrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_display_name: str
    risk_level: str
    estimation_method: str
    warnings: list[str] = Field(default_factory=list)
    current_weights: dict[str, str] = Field(default_factory=dict)
    moves: list[MovePayload] = Field(default_factory=list)


class _Digits(NamedTuple):
    sharpe: int
    vol: int
    ret: int


def _digits(shifts: list[SectorShift], risk_level: RiskLevel) -> _Digits:
    """Display precision, by the same rule the UI applies.

    **Mirror of `moveDigits` in frontend/lib/moves.ts — change both together.**
    The model quotes these strings verbatim, and the client renders the delta
    rows beside them from its own formatting, so if the two rules diverge the
    prose and the numbers next to it show the same quantity to different
    precision. Widen a figure whose own before/after collapses, and widen the
    figure the risk level ranks by when ties would hide the order.
    """

    def widen(pick, fmt, base: int, is_key: bool) -> int:
        hides_change = any(
            fmt(pick(s.metrics_before), base) == fmt(pick(s.metrics_after), base)
            for s in shifts
        )
        afters = [fmt(pick(s.metrics_after), base) for s in shifts]
        hides_order = is_key and len(set(afters)) != len(afters)
        return base + 1 if hides_change or hides_order else base

    return _Digits(
        sharpe=widen(
            lambda m: m.sharpe_ratio, fmt_num, 2, risk_level is RiskLevel.MODERATE
        ),
        vol=widen(
            lambda m: m.volatility, fmt_pct, 1, risk_level is RiskLevel.CONSERVATIVE
        ),
        ret=widen(
            lambda m: m.expected_return,
            fmt_pct,
            1,
            risk_level is RiskLevel.AGGRESSIVE,
        ),
    )


def build_payload(
    *,
    display_name: str,
    risk_level: RiskLevel,
    estimation_method: str,
    attribution: list[SectorAttribution],
    shifts: list[SectorShift],
) -> NarrationPayload:
    warnings: list[str] = []
    for shift in shifts:
        for w in shift.warnings:
            if w in _KNOWN_WARNINGS and w not in warnings:
                warnings.append(w)

    digits = _digits(shifts, risk_level)
    return NarrationPayload(
        model_display_name=display_name,
        risk_level=risk_level.value,
        estimation_method=estimation_method,
        warnings=warnings,
        current_weights={
            a.sector: fmt_pct(a.weight) for a in attribution if a.weight > 0
        },
        moves=[_move(s, digits) for s in shifts],
    )


def _move(shift: SectorShift, d: _Digits) -> MovePayload:
    b, a = shift.metrics_before, shift.metrics_after
    return MovePayload(
        from_sector=shift.from_sector,
        to_sector=shift.to_sector,
        move_pct=fmt_pct(shift.fraction, 0),
        vol_before_pct=fmt_pct(b.volatility, d.vol),
        vol_after_pct=fmt_pct(a.volatility, d.vol),
        vol_delta_pts=fmt_pts(a.volatility - b.volatility),
        return_before_pct=fmt_pct(b.expected_return, d.ret),
        return_after_pct=fmt_pct(a.expected_return, d.ret),
        return_delta_pts=fmt_pts(a.expected_return - b.expected_return),
        sharpe_before=fmt_num(b.sharpe_ratio, d.sharpe),
        sharpe_after=fmt_num(a.sharpe_ratio, d.sharpe),
        sharpe_delta=fmt_signed(a.sharpe_ratio - b.sharpe_ratio),
    )
