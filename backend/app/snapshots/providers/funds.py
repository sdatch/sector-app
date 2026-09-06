"""
Fund composition reference data — the sector breakdown of pooled vehicles.

A fund is not a sector, and pretending otherwise would corrupt attribution
(invariant: the sector mix must mean what it says). But excluding funds
outright means the app cannot analyze the portfolios most people actually hold,
which are mostly index funds. So a fund is *decomposed*: its value is spread
across the eleven GICS sectors in the proportions the fund itself holds.

Two honesty constraints are built into the shape of this table:

1. `equity_share` — the fraction of the fund that maps to a modelable GICS
   equity sector at all. A bond fund is 0.0 and stays excluded; a 60/40
   balanced fund is 0.6, and the remaining 0.4 is reported as an unmodeled
   sleeve rather than quietly inflating the equity weights.

2. `approximation` — a plain-language statement of what is being fudged, shown
   to the user. Decomposing an international fund onto US sector return series
   is a real compromise, and the app says so rather than hiding it.

These weights are static, rounded, long-run-typical allocations, NOT live fund
holdings — the same standing as the synthetic price series they sit beside. A
real provider would fetch actual holdings; the shape of this table is what it
would populate.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sector keys, matching providers.synthetic.SECTORS.
_IT = "Information Technology"
_HC = "Health Care"
_FIN = "Financials"
_CD = "Consumer Discretionary"
_COM = "Communication Services"
_IND = "Industrials"
_CS = "Consumer Staples"
_ENE = "Energy"
_UTL = "Utilities"
_RE = "Real Estate"
_MAT = "Materials"


@dataclass(frozen=True)
class FundComposition:
    """How one pooled vehicle maps onto the modelable sector universe."""

    name: str
    kind: str  # us_broad | us_style | international | balanced | bond
    equity_share: float  # fraction mapping to GICS sectors, in [0, 1]
    sector_weights: dict[str, float]  # normalized to 1.0 within the equity sleeve
    approximation: str | None = None

    @property
    def modelable(self) -> bool:
        return self.equity_share > 0.0 and bool(self.sector_weights)


def _norm(raw: dict[str, float]) -> dict[str, float]:
    """Normalize a hand-written breakdown to exactly 1.0.

    Written as readable percentages above; normalized here so a typo becomes a
    small proportional shift rather than weights that silently do not sum.
    Rounding residual is absorbed by the largest weight, because "sums to 1.0"
    has to be exact — these feed an allocation the contract validates.
    """
    total = sum(raw.values())
    if total <= 0:
        return {}
    out = {s: round(v / total, 6) for s, v in raw.items()}
    residual = 1.0 - sum(out.values())
    if residual:
        largest = max(out, key=out.__getitem__)
        out[largest] = round(out[largest] + residual, 6)
    return out


# --- Equity sector profiles (percentages; normalized on use) ----------------

_SP500 = {
    _IT: 32.0, _FIN: 13.0, _HC: 11.0, _CD: 10.0, _COM: 9.0, _IND: 8.0,
    _CS: 6.0, _ENE: 3.5, _UTL: 2.5, _MAT: 2.3, _RE: 2.2,
}
_US_TOTAL = {
    _IT: 30.0, _FIN: 13.5, _HC: 11.5, _CD: 10.5, _IND: 9.0, _COM: 8.5,
    _CS: 5.5, _ENE: 3.5, _RE: 3.0, _UTL: 2.5, _MAT: 2.5,
}
_NASDAQ100 = {
    _IT: 50.0, _COM: 15.0, _CD: 13.0, _HC: 6.0, _CS: 6.0, _IND: 4.0,
    _UTL: 1.5, _FIN: 2.0, _ENE: 1.0, _MAT: 1.0, _RE: 0.5,
}
_US_GROWTH = {
    _IT: 45.0, _CD: 15.0, _COM: 12.0, _HC: 8.0, _IND: 6.0, _FIN: 6.0,
    _CS: 3.0, _RE: 1.5, _UTL: 1.5, _MAT: 1.0, _ENE: 1.0,
}
_US_VALUE = {
    _FIN: 22.0, _HC: 15.0, _IND: 13.0, _CS: 10.0, _IT: 9.0, _ENE: 8.0,
    _UTL: 7.0, _CD: 6.0, _COM: 4.0, _MAT: 4.0, _RE: 2.0,
}
_US_SMALL = {
    _FIN: 17.0, _IND: 17.0, _HC: 15.0, _IT: 13.0, _CD: 12.0, _RE: 7.0,
    _ENE: 6.0, _MAT: 5.0, _CS: 4.0, _UTL: 3.0, _COM: 2.0,
}
_US_MID = {
    _IND: 19.0, _FIN: 16.0, _CD: 14.0, _IT: 11.0, _HC: 10.0, _RE: 7.0,
    _MAT: 6.0, _CS: 5.0, _ENE: 5.0, _UTL: 5.0, _COM: 2.0,
}
_INTL_DEVELOPED = {
    _FIN: 21.0, _IND: 16.0, _HC: 12.0, _CD: 11.0, _IT: 9.0, _CS: 8.0,
    _MAT: 7.0, _COM: 5.0, _ENE: 5.0, _UTL: 3.0, _RE: 2.0,
}
_INTL_EMERGING = {
    _IT: 24.0, _FIN: 23.0, _CD: 13.0, _COM: 10.0, _MAT: 7.0, _CS: 6.0,
    _IND: 6.0, _ENE: 5.0, _HC: 4.0, _UTL: 3.0, _RE: 2.0,
}
_INTL_TOTAL = {
    _FIN: 21.0, _IND: 14.0, _IT: 13.0, _CD: 11.0, _HC: 10.0, _CS: 7.0,
    _MAT: 7.0, _COM: 6.0, _ENE: 5.0, _UTL: 3.0, _RE: 3.0,
}
_GLOBAL = {
    _IT: 24.0, _FIN: 16.0, _HC: 11.0, _CD: 11.0, _IND: 11.0, _COM: 7.5,
    _CS: 6.0, _ENE: 4.0, _MAT: 4.0, _UTL: 3.0, _RE: 2.5,
}

_INTL_NOTE = (
    "International holdings are mapped onto US sector return series — the "
    "sector mix is right, but the returns and correlations modeled are US ones"
)
_SMALL_NOTE = (
    "Small- and mid-cap holdings are modeled with large-cap sector returns, "
    "which understates their volatility"
)
_BOND_SLEEVE_NOTE = (
    "Only the equity sleeve is modeled; the fixed-income portion is excluded "
    "from the sector mix"
)


def _fund(
    tickers: str,
    name: str,
    kind: str,
    profile: dict[str, float],
    equity_share: float = 1.0,
    approximation: str | None = None,
) -> dict[str, FundComposition]:
    comp = FundComposition(
        name=name,
        kind=kind,
        equity_share=equity_share,
        sector_weights=_norm(profile),
        approximation=approximation,
    )
    return {t: comp for t in tickers.split()}


FUND_COMPOSITION: dict[str, FundComposition] = {
    # -- US broad market ---------------------------------------------------
    **_fund(
        "SPY VOO IVV SPLG SPTM FXAIX VFIAX SWPPX SPY5 RSP",
        "S&P 500 index fund", "us_broad", _SP500,
    ),
    **_fund(
        "VTI ITOT SCHB VTSAX SWTSX FSKAX FNILX FZROX VV MGC SCHX",
        "US total-market index fund", "us_broad", _US_TOTAL,
    ),
    # -- US style / size ---------------------------------------------------
    **_fund("QQQ QQQM", "Nasdaq-100 fund", "us_style", _NASDAQ100),
    **_fund(
        "VUG IWF SCHG MGK SPYG",
        "US large-cap growth fund", "us_style", _US_GROWTH,
    ),
    **_fund(
        "VTV IWD SCHV SPYV VOE",
        "US large-cap value fund", "us_style", _US_VALUE,
    ),
    **_fund(
        "IWM VB VBR VXF VIOO",
        "US small-cap fund", "us_style", _US_SMALL,
        approximation=_SMALL_NOTE,
    ),
    **_fund(
        "IJH IJR VO MDY VOT",
        "US mid-cap fund", "us_style", _US_MID,
        approximation=_SMALL_NOTE,
    ),
    # -- International -----------------------------------------------------
    **_fund(
        "VXUS IXUS VEU FTIHX VTIAX",
        "Total international equity fund", "international", _INTL_TOTAL,
        approximation=_INTL_NOTE,
    ),
    **_fund(
        "EFA IEFA VEA SCHF VGK VPL EWJ VTMGX",
        "Developed-markets equity fund", "international", _INTL_DEVELOPED,
        approximation=_INTL_NOTE,
    ),
    **_fund(
        "VWO IEMG EEM SCHE INDA MCHI",
        "Emerging-markets equity fund", "international", _INTL_EMERGING,
        approximation=_INTL_NOTE,
    ),
    **_fund(
        "ACWI VT VTWAX",
        "Global all-cap equity fund", "international", _GLOBAL,
        approximation=_INTL_NOTE,
    ),
    # -- Balanced / target-date (partial equity) ---------------------------
    **_fund(
        "AOA VASGX", "Aggressive allocation fund (~80/20)", "balanced",
        _GLOBAL, equity_share=0.80, approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "AOR VSMGX", "Growth allocation fund (~60/40)", "balanced",
        _GLOBAL, equity_share=0.60, approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "VBIAX", "US balanced index fund (~60/40)", "balanced",
        _US_TOTAL, equity_share=0.60, approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "AOM VSCGX", "Moderate allocation fund (~40/60)", "balanced",
        _GLOBAL, equity_share=0.40, approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "AOK", "Conservative allocation fund (~30/70)", "balanced",
        _GLOBAL, equity_share=0.30, approximation=_BOND_SLEEVE_NOTE,
    ),
    # Target-date: equity share falls as the target year approaches.
    **_fund(
        "VFIFX VLXVX VTTSX", "Target-date fund (far-dated, ~90% equity)",
        "balanced", _GLOBAL, equity_share=0.90,
        approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "VFFVX VTTHX", "Target-date fund (mid-dated, ~85% equity)",
        "balanced", _GLOBAL, equity_share=0.85,
        approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "VTHRX", "Target-date fund (~70% equity)", "balanced", _GLOBAL,
        equity_share=0.70, approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "VTTVX", "Target-date fund (near-dated, ~45% equity)", "balanced",
        _GLOBAL, equity_share=0.45, approximation=_BOND_SLEEVE_NOTE,
    ),
    **_fund(
        "VTWNX VTXVX", "Target-date fund (at/past target, ~35% equity)",
        "balanced", _GLOBAL, equity_share=0.35,
        approximation=_BOND_SLEEVE_NOTE,
    ),
    # -- Fixed income: no equity sector exposure at all ---------------------
    **_fund(
        "BND AGG BNDX TLT IEF SHY LQD HYG JNK TIP VTIP MUB VCIT VCSH VGIT "
        "VGSH BSV BIV BLV SCHZ FXNAX VBTLX SGOV BIL SHV",
        "Bond fund", "bond", {}, equity_share=0.0,
    ),
}


def fund_kind_label(comp: FundComposition) -> str:
    """Short human label for the ingest report."""
    return comp.name
