"""
Data provider interface. The snapshot builder consumes RawMarketData and knows
nothing about where it came from — synthetic today, a free price API + Ken
French + FRED later, without touching the builder or engines (PRD NFR-7:
"snapshot builder tolerates provider substitution").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import numpy as np

from .funds import FundComposition


@dataclass(frozen=True)
class RawMarketData:
    """Everything a provider must supply. Daily series are aligned on the same
    T-length trading calendar. Sector series are *excess* daily simple returns
    (over the risk-free rate) so factor regressions are well-posed; the builder
    re-adds rf where total returns are needed."""

    snapshot_id: str
    prices_start: date
    prices_end: date
    risk_free_annual: float
    factor_data_vintage: date | None

    sectors: tuple[str, ...]  # canonical sector ordering (S,)
    factor_names: tuple[str, ...]  # canonical factor ordering (F,)

    sector_excess_returns: np.ndarray  # (T, S) daily, over rf
    factor_returns: np.ndarray  # (T, F) daily (MKT already excess)
    market_caps: np.ndarray  # (S,) relative capitalization weights

    # ticker -> sector, the universe the app can risk-model. Tickers outside
    # this table AND outside fund_composition are rejected at ingest with
    # `unknown_ticker`.
    ticker_sector: dict[str, str]
    # ticker -> last price, for CSV valuation (weights derived from quantity).
    # Covers fund tickers as well as single-sector ones.
    ticker_price: dict[str, float]
    # ticker -> sector breakdown for pooled vehicles. A fund holds many sectors
    # at once, so it is decomposed at evaluation time rather than forced into
    # one. See providers/funds.py.
    fund_composition: dict[str, FundComposition]


class MarketDataProvider(Protocol):
    def fetch(self) -> RawMarketData: ...
