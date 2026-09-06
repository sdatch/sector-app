"""
Deterministic synthetic provider — the default so the whole app runs offline
with zero API keys (chosen in build kickoff). Sector returns are generated
*from* a Fama-French-style factor model plus idiosyncratic noise, so the FF
engine's regressions recover real signal rather than fitting noise, and BL /
MC see a realistic covariance structure.

Determinism: everything derives from a fixed integer seed, so the same
snapshot_id always yields bit-identical artifacts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import numpy as np

# Bumped when the generation math changes in a way that should invalidate
# already-persisted artifacts. The ticker universe is fingerprinted separately
# (it is data, not math), so growing it does not need a bump here.
BUILD_VERSION = "1"

from .base import RawMarketData
from .funds import FUND_COMPOSITION

# GICS 11 sectors — the canonical universe.
SECTORS: tuple[str, ...] = (
    "Information Technology",
    "Health Care",
    "Financials",
    "Consumer Discretionary",
    "Communication Services",
    "Industrials",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
    "Materials",
)

# Fama-French 5 factors.
FACTORS: tuple[str, ...] = ("MKT", "SMB", "HML", "RMW", "CMA")

# Annualized factor premia and vols (plausible long-run values).
_FACTOR_PREMIA = np.array([0.060, 0.020, 0.030, 0.025, 0.015])
_FACTOR_VOL = np.array([0.16, 0.10, 0.09, 0.07, 0.06])

# Ticker -> sector reference table. Broad enough that a typical retail brokerage
# export resolves rather than being mostly rejected: large/mid-cap US names
# across all eleven sectors, plus the single-sector ETFs people actually hold.
#
# Only tickers that map to EXACTLY ONE sector belong here. Broad-market and
# multi-sector funds (SPY, VTI, QQQ, target-date funds) are deliberately absent
# and are classified separately by the ingester — see portfolios/ingest.py — so
# they get an explanatory rejection rather than a misleading sector assignment.
#
# A real MarketDataProvider supplies the full reference table; this is the
# offline stand-in. Order is irrelevant: prices are hashed per ticker, so adding
# names here never perturbs the price of an existing one.
_TICKER_SECTOR: dict[str, str] = {
    # -- Information Technology ------------------------------------------
    **{
        t: "Information Technology"
        for t in (
            "AAPL MSFT NVDA AVGO ORCL CRM ADBE AMD ACN CSCO INTC TXN QCOM IBM "
            "INTU NOW AMAT MU ADI LRCX KLAC SNPS CDNS PANW ANET MSI ROP ADSK "
            "FTNT NXPI MCHP APH TEL GLW HPQ HPE DELL WDC STX NTAP KEYS TER "
            "SWKS MPWR ON ZBRA JNPR CTSH IT GDDY AKAM FSLR ENPH TYL PTC ANSS "
            "CRWD DDOG SNOW MDB NET ZS TEAM WDAY VEEV HUBS SMCI ARM PLTR "
            "XLK VGT IYW FTEC IGV SOXX SMH"
        ).split()
    },
    # -- Health Care ------------------------------------------------------
    **{
        t: "Health Care"
        for t in (
            "JNJ UNH LLY PFE MRK ABBV TMO ABT DHR BMY AMGN GILD CVS CI ELV "
            "ISRG SYK BSX MDT VRTX REGN ZTS BDX HCA MCK COR CAH BIIB MRNA "
            "IQV A IDXX RMD DXCM EW HOLX BAX ZBH STE WAT MTD PODD ALGN "
            "CNC HUM DVA UHS VTRS OGN TECH CRL LH DGX"
            " XLV VHT IYH FHLC IBB XBI IHI"
        ).split()
    },
    # -- Financials -------------------------------------------------------
    **{
        t: "Financials"
        for t in (
            "BRK-B JPM BAC WFC GS MS C SCHW BLK SPGI AXP BX CB PGR MMC AON "
            "ICE CME AJG PNC USB TFC COF BK STT NTRS FITB HBAN RF CFG KEY "
            "MTB ALL TRV AIG MET PRU AFL HIG PFG L WRB CINF GL AIZ ACGL "
            "EG RJF AMP TROW BEN IVZ NDAQ MCO MSCI FI FIS GPN DFS SYF "
            "XLF VFH IYF FNCL KRE KBE"
        ).split()
    },
    # -- Consumer Discretionary -------------------------------------------
    **{
        t: "Consumer Discretionary"
        for t in (
            "AMZN TSLA HD MCD NKE LOW SBUX TJX BKNG ORLY AZO CMG ABNB MAR "
            "HLT GM F RCL CCL NCLH LVS WYNN MGM DRI YUM DPZ ROST BURL ULTA "
            "LULU DECK TPR RL PVH GPS BBY DKS WSM TSCO GRMN POOL LKQ APTV "
            "BWA LEA DHI LEN NVR PHM TOL EBAY ETSY W CHWY DASH EXPE"
            " XLY VCR IYC FDIS"
        ).split()
    },
    # -- Communication Services -------------------------------------------
    **{
        t: "Communication Services"
        for t in (
            "GOOGL GOOG META NFLX DIS VZ T CMCSA TMUS CHTR EA TTWO RBLX "
            "WBD PARA FOX FOXA NWS NWSA OMC IPG LYV MTCH PINS SNAP SPOT "
            "TTD LUMN DISH ZM"
            " XLC VOX IYZ FCOM"
        ).split()
    },
    # -- Industrials ------------------------------------------------------
    **{
        t: "Industrials"
        for t in (
            "CAT BA HON GE UPS RTX LMT UNP DE ETN ITW MMM NOC GD CSX NSC "
            "FDX EMR PH CMI PCAR ROK AME FAST GWW URI PWR CARR OTIS JCI "
            "TT IR DOV XYL SWK MAS AOS PNR TDG HWM LHX TXT HII AXON WM RSG "
            "VRSK CPRT ODFL JBHT CHRW EXPD LUV DAL UAL AAL ALK"
            " XLI VIS IYJ FIDU ITA JETS"
        ).split()
    },
    # -- Consumer Staples -------------------------------------------------
    **{
        t: "Consumer Staples"
        for t in (
            "PG KO PEP WMT COST MDLZ MO PM CL KMB GIS KHC HSY SYY KR STZ "
            "K MKC CHD CLX SJM CAG CPB HRL TAP TSN ADM BG DG DLTR WBA "
            "EL KVUE MNST KDP CASY"
            " XLP VDC IYK FSTA"
        ).split()
    },
    # -- Energy -----------------------------------------------------------
    **{
        t: "Energy"
        for t in (
            "XOM CVX COP SLB EOG MPC PSX VLO OXY PXD HES WMB OKE KMI LNG "
            "TRGP BKR HAL DVN FANG CTRA APA MRO EQT AR RRC SWN OVV DINO "
            "XLE VDE IYE FENY XOP OIH AMLP"
        ).split()
    },
    # -- Utilities --------------------------------------------------------
    **{
        t: "Utilities"
        for t in (
            "NEE DUK SO D AEP SRE EXC XEL ED PEG WEC ES AEE DTE PPL FE "
            "CMS CNP ATO NI LNT EVRG AES PNW NRG CEG VST AWK WTRG"
            " XLU VPU IDU FUTY"
        ).split()
    },
    # -- Real Estate ------------------------------------------------------
    **{
        t: "Real Estate"
        for t in (
            "PLD AMT SPG EQIX CCI PSA O WELL DLR VICI AVB EQR EXR MAA UDR "
            "ESS CPT INVH AMH ARE BXP VTR HST REG FRT KIM CBRE IRM SBAC "
            "WY DOC"
            " XLRE VNQ IYR FREL SCHH"
        ).split()
    },
    # -- Materials --------------------------------------------------------
    **{
        t: "Materials"
        for t in (
            "LIN SHW FCX APD ECL NEM DOW DD PPG NUE VMC MLM CTVA IFF ALB "
            "LYB CE EMN MOS CF STLD RS PKG IP AMCR AVY BALL SEE WRK CLF X"
            " XLB VAW IYM FMAT GLD SLV"
        ).split()
    },
}

# Relative market caps by sector (drives BL equilibrium). Loosely mirrors a
# cap-weighted US index: IT largest, Utilities/Materials/RE small.
_SECTOR_CAP = np.array(
    [0.29, 0.13, 0.13, 0.10, 0.09, 0.08, 0.06, 0.04, 0.025, 0.02, 0.025]
)

_TRADING_DAYS = 252


class SyntheticProvider:
    """Generates a full, deterministic RawMarketData from a seed."""

    def __init__(
        self,
        snapshot_id: str = "synthetic-2024-12-31",
        seed: int = 20241231,
        n_days: int = 10 * _TRADING_DAYS,  # long history => stable premia/cov
        risk_free_annual: float = 0.043,
        prices_end: date = date(2024, 12, 31),
    ) -> None:
        self.snapshot_id = snapshot_id
        self.seed = seed
        self.n_days = n_days
        self.risk_free_annual = risk_free_annual
        self.prices_end = prices_end

    def reference_fingerprint(self) -> str:
        """Cheap hash of everything that determines this provider's output.

        Persisted alongside the artifact so a stale one is detected and rebuilt
        rather than served silently — growing the ticker universe used to have
        no effect on any environment that already had an artifacts volume.
        Deliberately computed from module constants, so checking it costs
        nothing and does not require running the expensive build.
        """
        payload = json.dumps(
            {
                "build": BUILD_VERSION,
                "seed": self.seed,
                "n_days": self.n_days,
                "risk_free": self.risk_free_annual,
                "prices_end": self.prices_end.isoformat(),
                "sectors": list(SECTORS),
                "factors": list(FACTORS),
                "tickers": sorted(_TICKER_SECTOR.items()),
                "funds": sorted(
                    (t, c.name, c.equity_share, sorted(c.sector_weights.items()))
                    for t, c in FUND_COMPOSITION.items()
                ),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def fetch(self) -> RawMarketData:
        rng = np.random.default_rng(self.seed)
        S, F, T = len(SECTORS), len(FACTORS), self.n_days

        # Daily factor returns ~ Normal(premia/252, vol/sqrt(252)).
        f_mu_daily = _FACTOR_PREMIA / _TRADING_DAYS
        f_sd_daily = _FACTOR_VOL / np.sqrt(_TRADING_DAYS)
        factor_returns = rng.normal(f_mu_daily, f_sd_daily, size=(T, F))

        # Sector factor loadings: MKT near 1, others spread around 0.
        loadings = np.column_stack(
            [
                rng.uniform(0.75, 1.20, size=S),  # MKT
                rng.uniform(-0.40, 0.60, size=S),  # SMB
                rng.uniform(-0.45, 0.55, size=S),  # HML
                rng.uniform(-0.35, 0.45, size=S),  # RMW
                rng.uniform(-0.35, 0.40, size=S),  # CMA
            ]
        )

        # Idiosyncratic daily vol per sector (10%–22% annualized).
        resid_vol_annual = rng.uniform(0.10, 0.22, size=S)
        resid_daily = rng.normal(
            0.0, resid_vol_annual / np.sqrt(_TRADING_DAYS), size=(T, S)
        )

        # Sector EXCESS daily returns = loadings @ factor + idiosyncratic.
        sector_excess = factor_returns @ loadings.T + resid_daily  # (T, S)

        return RawMarketData(
            snapshot_id=self.snapshot_id,
            prices_start=self.prices_end
            - timedelta(days=int(self.n_days * 365 / _TRADING_DAYS)),
            prices_end=self.prices_end,
            risk_free_annual=self.risk_free_annual,
            factor_data_vintage=self.prices_end,
            sectors=SECTORS,
            factor_names=FACTORS,
            sector_excess_returns=sector_excess,
            factor_returns=factor_returns,
            market_caps=_SECTOR_CAP.copy(),
            ticker_sector=dict(_TICKER_SECTOR),
            ticker_price=self._synthetic_prices(),
            fund_composition=dict(FUND_COMPOSITION),
        )

    def _synthetic_prices(self) -> dict[str, float]:
        """Stable per-ticker prices in a sane range.

        Hashed per ticker rather than drawn from the shared generator, so a
        ticker's price depends only on (seed, ticker) — growing the universe
        never shifts the price of an existing name, and therefore never
        silently re-weights a saved portfolio.

        Funds are priced too: a decomposed fund is still valued from quantity,
        so an unpriced fund ticker would be worth zero and vanish.
        """
        tickers = set(_TICKER_SECTOR) | set(FUND_COMPOSITION)
        return {t: _hashed_price(t, self.seed) for t in sorted(tickers)}


def _hashed_price(ticker: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}:{ticker}".encode()).digest()
    unit = int.from_bytes(digest[:8], "big") / 2**64  # [0, 1)
    return round(25.0 + unit * 525.0, 2)
