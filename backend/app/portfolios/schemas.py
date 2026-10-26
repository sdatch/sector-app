"""Portfolio + ingestion wire schemas (user_model_spec §3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.comparison import SectorWeight

from .sectors import SECTOR_CODE

# Where a stored position's sector came from. "reference" is the curated table
# (and NULL in the database, so rows committed before this existed need no
# backfill); "model" is a lookup suggestion the user accepted unchanged; "user"
# is a sector the user picked. Either way a person confirmed it — the lookup
# only ever proposes.
SectorSource = Literal["reference", "model", "user"]


class SectorOverride(BaseModel):
    """A sector the user has confirmed for one ticker in the preview."""

    sector: str
    source: Literal["model", "user"] = "user"

    @field_validator("sector")
    @classmethod
    def known_sector(cls, v: str) -> str:
        if v not in SECTOR_CODE:
            raise ValueError(f"Unknown sector '{v}'")
        return v


class IngestAccepted(BaseModel):
    ticker: str
    quantity: float
    sector: str
    last_price: float
    value: float
    weight: float
    # Provenance so the preview UI can show the file back in its own order,
    # interleaved with the rows that did not make it.
    row: int = 0
    note: str | None = None
    sector_source: SectorSource = "reference"
    # Pooled vehicles only. `sector` carries the FUND_SECTOR sentinel and the
    # real exposure lives here: sector -> share of this holding's equity
    # sleeve. `equity_share` < 1 means part of the holding (bonds, cash) has no
    # sector exposure to model.
    is_fund: bool = False
    fund_name: str | None = None
    equity_share: float = 1.0
    sector_breakdown: dict[str, float] | None = None


class IngestRejected(BaseModel):
    row: int
    raw: str
    reason: str
    resolution: str | None = None
    # The normalized symbol, for rows that got far enough to have one
    # (unknown_ticker, no_price): what a sector override or lookup is keyed on.
    ticker: str | None = None
    # An unrecognized ticker this snapshot can still price: the user may give
    # it a sector (by hand or on a lookup suggestion) and it is then included.
    can_assign_sector: bool = False


class IngestTotals(BaseModel):
    value: float
    positions: int
    coverage_pct: float
    # Share of the priceable account with no modelable sector exposure: the
    # fixed-income sleeve of balanced funds PLUS wholly-excluded bond funds,
    # over (accepted value + excluded fund value). Surfaced so the UI can say a
    # 60/40 portfolio is being modeled as its 60. Unknown tickers are not in
    # here — they have no price, so their share is not computable.
    unmodeled_share: float = 0.0


class IngestReport(BaseModel):
    accepted: list[IngestAccepted]
    rejected: list[IngestRejected]
    warnings: list[str] = Field(default_factory=list)
    totals: IngestTotals


class AcceptedRow(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    # Set only when the user confirmed a sector other than the reference one.
    # Omitted, the server resolves the sector itself exactly as before.
    sector: str | None = None
    sector_source: Literal["model", "user"] | None = None

    @model_validator(mode="after")
    def source_needs_sector(self) -> AcceptedRow:
        if self.sector is not None and self.sector not in SECTOR_CODE:
            raise ValueError(f"Unknown sector '{self.sector}'")
        if self.sector is None:
            self.sector_source = None
        elif self.sector_source is None:
            self.sector_source = "user"
        return self


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_default: bool = False
    # Exactly one of: accepted rows (CSV path) or sector_weights (manual path).
    accepted: list[AcceptedRow] | None = None
    sector_weights: list[SectorWeight] | None = None

    @model_validator(mode="after")
    def one_mode(self) -> PortfolioCreate:
        if bool(self.accepted) == bool(self.sector_weights):
            raise ValueError("Provide exactly one of: accepted, sector_weights")
        if self.sector_weights:
            total = sum(w.weight for w in self.sector_weights)
            if abs(total - 1.0) > 1e-4:
                raise ValueError("sector_weights must sum to 1.0")
        return self


class PositionRead(BaseModel):
    ticker: str
    quantity: float
    sector: str
    sector_source: SectorSource = "reference"


class PortfolioRead(BaseModel):
    id: uuid.UUID
    name: str
    source: str
    is_default: bool
    created_at: datetime
    positions: list[PositionRead]


class AllocationRead(BaseModel):
    """A stored portfolio resolved against the active snapshot — the read-only
    view of service.ResolvedAllocation.

    `sector_weights` sums to 1.0 over the *modelable equity sleeve*;
    `unmodeled_share` is the fraction of portfolio value that sleeve leaves out
    (the fixed-income side of a balanced fund, bullion, commodity funds), and
    `approximations` is what fund decomposition is fudging. The comparison path
    consumes only the weights, so a caller that wants to tell the user which
    part of their money the numbers cover asks here.
    """

    portfolio_id: uuid.UUID
    snapshot_id: str
    sector_weights: list[SectorWeight]
    unmodeled_share: float = 0.0
    approximations: list[str] = Field(default_factory=list)
