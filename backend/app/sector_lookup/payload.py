"""
The privacy boundary (PRD NFR-3).

Everything that leaves this process for the lookup model is built here. Unlike
narration, this feature has to send tickers — a symbol is the question — so the
boundary is drawn one step tighter around them: the payload is a list of
symbols and nothing else. No quantity, value, weight, portfolio name, file
content or user id has a field to travel in. The model is `extra="forbid"` and
frozen, and a test freezes its field set, so a leaky field fails CI.

A symbol is also pattern-checked. Broker exports put free text in the ticker
column (account names, "Pending activity"), and a row that is not a ticker must
not be shipped off-process just because it sat in that column.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,15}$")


def normalize_symbol(raw: str) -> str:
    """Same normalization as ingest._normalize_ticker (BRK.B -> BRK-B)."""
    return raw.strip().upper().replace(".", "-")


def is_symbol(value: str) -> bool:
    return bool(_SYMBOL.match(value))


def _check(value: str) -> str:
    if not is_symbol(value):
        raise ValueError(f"not a ticker symbol: {value!r}")
    return value


TickerSymbol = Annotated[str, AfterValidator(_check)]


class LookupPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tickers: tuple[TickerSymbol, ...]


def build_payload(tickers: list[str]) -> LookupPayload:
    """Deduplicated, normalized, sorted — so a batch is a pure function of the
    set of symbols, whatever order the file listed them in."""
    return LookupPayload(tickers=tuple(sorted({normalize_symbol(t) for t in tickers})))
