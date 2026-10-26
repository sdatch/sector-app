"""
What the lookup model returns: a classification per symbol, never a weight,
a price or a recommendation.

`sector` is constrained to the eleven names the models are built on, so a reply
cannot invent a twelfth; validate.py checks it again regardless, because a
schema is a request to the model and the validator is the guarantee.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.portfolios.sectors import SECTOR_CODE

# The eleven GICS sector names, as a Literal built from the one table the app
# already treats as canonical (portfolios/sectors.py).
SectorName = Literal[tuple(SECTOR_CODE)]  # type: ignore[valid-type]

Kind = Literal["stock", "fund", "non_equity", "unknown"]
Confidence = Literal["high", "medium", "low"]


class TickerClassification(BaseModel):
    ticker: str
    company_name: str | None = None
    kind: Kind
    # Present exactly when kind == "stock". A fund is never given one sector
    # (CLAUDE.md invariant 8), and "unknown" means unknown, not a guess.
    sector: SectorName | None = None
    confidence: Confidence
    rationale: str = Field(description="One sentence: what the company does.")
    searched: bool = Field(
        description="True if a web search informed this classification."
    )


class LookupOutput(BaseModel):
    classifications: list[TickerClassification]
