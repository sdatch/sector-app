"""
The honesty boundary (PRD NFR-5, §3 non-goals).

Generated prose sits beside numbers the user is told are traceable, so it is
checked against the figures it was given before anyone sees it. Any failure
rejects the whole set for that model — never a mix of checked and unchecked
copy — and the client falls back to its own deterministic wording.

The number check is numeric, not textual. The payload holds display strings, so
"16.30%" and "16.3%" are the same claim and both pass, while a figure that was
never supplied fails whatever its formatting. Signs are compared on absolute
value, because prose legitimately carries the direction as a word ("a 1.2 point
drop" for a supplied -1.20).
"""

from __future__ import annotations

import re
from enum import Enum

from .payload import NarrationPayload
from .schema import NarrationOutput

MIN_LEN = 20
MAX_LEN = 450

# Tolerated all-caps tokens; anything else of that shape reads as a ticker.
# "ETF" is NOT tolerated: the prompt forbids fund talk, so a reply reaching for
# it has strayed. Nor are VAR/CVAR — we supply no such figure, so naming one
# means inventing it.
_CAPS_OK = frozenset({"US", "GICS"})
_TICKER_RE = re.compile(r"\$[A-Za-z]|\b[A-Z]{2,5}\b")

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
# Small counts the copy may use without them being supplied ("all three moves").
_FREE_NUMBERS = {0.0, 1.0, 2.0, 3.0}
_NUMBER_TOLERANCE = 1e-9

# Advice verbs, and the certainty words that turn a model estimate into a
# promise. Collisions with innocent phrasing ("your holdings") are accepted:
# the cost is a fallback to deterministic copy, which is the safe direction.
#
# Three near-misses are deliberately absent, because their innocent use is far
# more likely than their trading use and a needless fallback makes the whole
# layer look broken: "order" ("in order to"), bare "short" ("short-term", which
# \b still matches through the hyphen), and "will". "will" is a genuine promise
# word, so the system prompt steers away from it rather than this list policing
# it — steer first, enforce only what must be enforced.
_FORBIDDEN_TERMS = frozenset(
    """
    buy buys buying bought sell sells selling sold hold holds holding holdings
    trade trades trading purchase purchases purchasing execute shorting
    rebalance rebalancing reallocate recommend recommends recommended
    recommendation advise advises advice should must guarantee guaranteed
    guarantees ensure ensures
    """.split()
)
_TERM_RE = re.compile(
    r"\b(" + "|".join(sorted(_FORBIDDEN_TERMS)) + r")\b", re.IGNORECASE
)

# Spelled-out quantities. "third" is omitted on purpose — it is far more often
# the ordinal ("ranks this third") than a fraction, and the fraction use is
# caught by the article form below.
_NUMBER_WORDS = frozenset(
    """
    four five six seven eight nine ten eleven twelve thirteen fourteen fifteen
    sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy
    eighty ninety hundred thousand million billion double triple twice
    """.split()
)
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(_NUMBER_WORDS)) + r")\b", re.IGNORECASE
)
_FRACTION_RE = re.compile(r"\b(a|one)\s+(third|quarter|half)\b", re.IGNORECASE)


class RejectReason(str, Enum):
    SHAPE_MISMATCH = "shape_mismatch"
    EMPTY = "empty"
    TOO_LONG = "too_long"
    FOREIGN_SECTOR = "foreign_sector"
    TICKER_LIKE = "ticker_like"
    TRADE_LANGUAGE = "trade_language"
    INVENTED_NUMBER = "invented_number"
    NUMBER_WORD = "number_word"


def allowed_numbers(payload: NarrationPayload) -> set[float]:
    """Every number we supplied, as absolute values."""
    out = set(_FREE_NUMBERS)
    for token in _NUMBER_RE.findall(payload.model_dump_json()):
        value = _parse(token)
        if value is not None:
            out.add(value)
    return out


def _parse(token: str) -> float | None:
    try:
        return abs(float(token.replace(",", "").replace("+", "")))
    except ValueError:
        return None


def validate_output(
    parsed: NarrationOutput | None,
    payload: NarrationPayload,
    all_sectors: tuple[str, ...] | list[str] = (),
) -> RejectReason | None:
    """None when the output may be shown; otherwise why it may not."""
    if parsed is None:
        return RejectReason.SHAPE_MISMATCH

    # 0. Shape — one entry per move, same pairs, same order. Without this
    #    nothing stops an invented fourth move or a silently reordered list.
    if len(parsed.moves) != len(payload.moves):
        return RejectReason.SHAPE_MISMATCH
    for got, want in zip(parsed.moves, payload.moves):
        if (got.from_sector, got.to_sector) != (want.from_sector, want.to_sector):
            return RejectReason.SHAPE_MISMATCH

    named = {m.from_sector for m in payload.moves} | {
        m.to_sector for m in payload.moves
    }
    named |= set(payload.current_weights)
    # Longest first so "Consumer Staples" is not masked by a shorter name.
    foreign = sorted(
        (s for s in all_sectors if s not in named), key=len, reverse=True
    )
    numbers = allowed_numbers(payload)

    for move in parsed.moves:
        reason = _check_text(move.text, foreign, numbers)
        if reason is not None:
            return reason
    return None


def _check_text(
    text: str, foreign: list[str], numbers: set[float]
) -> RejectReason | None:
    stripped = text.strip()
    if len(stripped) < MIN_LEN:
        return RejectReason.EMPTY
    if len(stripped) > MAX_LEN:
        return RejectReason.TOO_LONG

    for sector in foreign:
        if re.search(rf"\b{re.escape(sector)}\b", stripped, re.IGNORECASE):
            return RejectReason.FOREIGN_SECTOR

    if _TICKER_RE.search(_without_ok_caps(stripped)):
        return RejectReason.TICKER_LIKE

    if _TERM_RE.search(stripped):
        return RejectReason.TRADE_LANGUAGE

    if _NUMBER_WORD_RE.search(stripped) or _FRACTION_RE.search(stripped):
        return RejectReason.NUMBER_WORD

    for token in _NUMBER_RE.findall(stripped):
        value = _parse(token)
        if value is None:
            return RejectReason.INVENTED_NUMBER
        if not any(abs(value - a) <= _NUMBER_TOLERANCE for a in numbers):
            return RejectReason.INVENTED_NUMBER

    return None


def _without_ok_caps(text: str) -> str:
    for token in _CAPS_OK:
        text = re.sub(rf"\b{token}\b", "", text)
    return text
