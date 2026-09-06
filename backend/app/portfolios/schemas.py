"""Portfolio + ingestion wire schemas (user_model_spec §3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.contracts.comparison import SectorWeight


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


class PortfolioRead(BaseModel):
    id: uuid.UUID
    name: str
    source: str
    is_default: bool
    created_at: datetime
    positions: list[PositionRead]
