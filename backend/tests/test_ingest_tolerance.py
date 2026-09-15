"""Ingestion tolerance for real broker exports.

Regression cover for the failure that made a full brokerage CSV render as a
three-position portfolio: the header was assumed to be on row 1, so any export
with a preamble fell back to positional parsing, and every recognizable index
fund came back as an indistinguishable `unknown_ticker`.
"""

from __future__ import annotations

import pytest

from app.portfolios.ingest import IngestError, parse_csv
from app.snapshots.providers.synthetic import SyntheticProvider


@pytest.fixture(scope="module")
def universe():
    raw = SyntheticProvider().fetch()
    return raw.ticker_sector, raw.ticker_price, raw.fund_composition


# A Fidelity/Schwab-shaped export: account preamble, a blank line, the real
# header, positions, a recognized fund, an unknown name, then summary lines.
BROKER_CSV = b"""Brokerage Account XXXX-1234
Positions as of 08/27/2026

Symbol,Description,Quantity,Last Price,Current Value
AAPL,APPLE INC,120,$220.15,"$26,418.00"
BRK.B,BERKSHIRE HATHAWAY CL B,30,$450.00,"$13,500.00"
XOM,EXXON MOBIL CORP,150,$115.00,"$17,250.00"
VOO,VANGUARD S&P 500 ETF,50,$500.00,"$25,000.00"
MYPRIVATEFUND,SOME PRIVATE PLACEMENT,10,$100.00,"$1,000.00"
Cash,CASH & CASH INVESTMENTS,1500,,"$1,500.00"
Total,,,,"$83,168.00"
"""


def test_header_found_below_preamble(universe):
    """The header sits on line 4, not line 1 — positions must still resolve."""
    report = parse_csv(BROKER_CSV, *universe)
    assert {a.ticker for a in report.accepted} == {"AAPL", "BRK-B", "XOM", "VOO"}


def test_row_numbers_are_true_file_lines(universe):
    """Line numbers must survive blank-line skipping, or the preview points
    the user at the wrong row of their file."""
    report = parse_csv(BROKER_CSV, *universe)
    by_ticker = {a.ticker: a.row for a in report.accepted}
    assert by_ticker["AAPL"] == 5  # 2 preamble + 1 blank + 1 header
    assert by_ticker["BRK-B"] == 6
    assert by_ticker["XOM"] == 7


def test_broad_market_fund_is_decomposed_not_rejected(universe):
    """VOO is accepted and carries the sector breakdown it actually holds."""
    report = parse_csv(BROKER_CSV, *universe)
    voo = next(a for a in report.accepted if a.ticker == "VOO")
    assert voo.is_fund and voo.fund_name
    assert voo.equity_share == 1.0
    assert voo.sector_breakdown is not None
    assert sum(voo.sector_breakdown.values()) == pytest.approx(1.0)
    # An S&P 500 fund is tech-heavy but genuinely spread across all eleven.
    assert len(voo.sector_breakdown) == 11
    assert voo.sector_breakdown["Information Technology"] > 0.25

    unknown = next(r for r in report.rejected if r.raw.startswith("MYPRIVATE"))
    assert unknown.reason == "unknown_ticker"


def test_summary_lines_reported_not_silently_dropped(universe):
    report = parse_csv(BROKER_CSV, *universe)
    skipped = {r.raw.split(",")[0] for r in report.rejected if r.reason == "summary_line"}
    assert skipped == {"Cash", "Total"}


def test_coverage_counts_only_genuinely_lost_holdings(universe):
    """4 accepted of 5 real holdings — VOO now resolves; only the private
    placement is lost. Cash and the total line are not holdings and must not
    flatter the number."""
    report = parse_csv(BROKER_CSV, *universe)
    assert report.totals.coverage_pct == pytest.approx(4 / 5)


def test_normalized_ticker_carries_note_on_accepted_row(universe):
    report = parse_csv(BROKER_CSV, *universe)
    brk = next(a for a in report.accepted if a.ticker == "BRK-B")
    assert brk.note and "BRK.B" in brk.note


def test_headerless_positional_csv_still_works(universe):
    """No recognizable header => canonical [ticker, quantity] over every row."""
    report = parse_csv(b"AAPL,10\nMSFT,5\n", *universe)
    assert {a.ticker for a in report.accepted} == {"AAPL", "MSFT"}
    assert [a.row for a in report.accepted] == [1, 2]


def test_universe_covers_every_sector(universe):
    """A portfolio spread across the eleven GICS sectors must be modelable."""
    ticker_sector, _, _ = universe
    assert len(set(ticker_sector.values())) == 11
    assert len(ticker_sector) > 400


def test_prices_are_order_independent():
    """Adding tickers must never shift an existing ticker's price, or saved
    portfolios would silently re-weight."""
    prices = SyntheticProvider().fetch().ticker_price
    again = SyntheticProvider().fetch().ticker_price
    assert prices["AAPL"] == again["AAPL"]
    assert all(25.0 <= p <= 550.0 for p in prices.values())


def test_oversized_file_rejected(universe):
    rows = b"Ticker,Quantity\n" + b"AAPL,1\n" * 501
    with pytest.raises(IngestError):
        parse_csv(rows, *universe)


# --- persisted-artifact staleness -------------------------------------------


def test_stale_artifact_is_rebuilt_not_served(tmp_path, monkeypatch):
    """An artifacts volume built with an older ticker universe must not keep
    being served. This is what made a rebuilt container still reject tickers
    the running code recognized."""
    from app.snapshots import artifacts as art
    from app.snapshots.providers import synthetic as syn

    snap = "synthetic-staleness-test"

    # Build + persist against a deliberately tiny universe.
    monkeypatch.setattr(syn, "_TICKER_SECTOR", {"AAPL": "Information Technology"})
    first = art.ensure_bundle(snap, tmp_path)
    assert set(first.ticker_sector) == {"AAPL"}

    # Universe grows; the persisted artifact is now stale.
    monkeypatch.setattr(
        syn,
        "_TICKER_SECTOR",
        {"AAPL": "Information Technology", "XOM": "Energy"},
    )
    second = art.ensure_bundle(snap, tmp_path)
    assert set(second.ticker_sector) == {"AAPL", "XOM"}, (
        "stale artifact served instead of rebuilt"
    )

    # Unchanged inputs must still hit the persisted artifact (no rebuild churn).
    third = art.ensure_bundle(snap, tmp_path)
    assert set(third.ticker_sector) == {"AAPL", "XOM"}
    assert third.ticker_price["AAPL"] == second.ticker_price["AAPL"]


# --- fund decomposition ------------------------------------------------------


def test_bond_fund_has_no_equity_exposure(universe):
    """A pure bond fund cannot be decomposed into equity sectors and must say
    so, rather than being called an unknown ticker."""
    csv = b"Symbol,Quantity\nBND,100\nAGG,50\n"
    report = parse_csv(csv, *universe)
    assert report.accepted == []
    assert {r.reason for r in report.rejected} == {"no_equity_exposure"}


def test_balanced_fund_reports_its_unmodeled_sleeve(universe):
    """A 60/40 fund is modeled as its 60 — the other 40 must be reported, not
    silently folded into the equity weights."""
    csv = b"Symbol,Quantity\nAOR,100\n"
    report = parse_csv(csv, *universe)
    aor = report.accepted[0]
    assert aor.is_fund and aor.equity_share == pytest.approx(0.60)
    assert report.totals.unmodeled_share == pytest.approx(0.40)


def test_every_fund_profile_is_normalized_and_in_universe():
    """Guards the hand-written tables in providers/funds.py: weights must sum
    to 1.0 within the equity sleeve, and name only real GICS sectors."""
    from app.snapshots.providers.funds import FUND_COMPOSITION
    from app.snapshots.providers.synthetic import SECTORS

    for ticker, comp in FUND_COMPOSITION.items():
        assert 0.0 <= comp.equity_share <= 1.0, ticker
        if not comp.modelable:
            assert comp.sector_weights == {}, ticker
            continue
        assert sum(comp.sector_weights.values()) == pytest.approx(1.0), ticker
        assert set(comp.sector_weights) <= set(SECTORS), ticker
        assert all(w >= 0 for w in comp.sector_weights.values()), ticker


def test_funds_are_priced():
    """An unpriced fund ticker would be valued at zero and silently vanish."""
    raw = SyntheticProvider().fetch()
    for ticker in raw.fund_composition:
        assert raw.ticker_price.get(ticker, 0.0) > 0, ticker


def _fake_portfolio(source, positions):
    """Minimal stand-in for the ORM object resolve_allocation reads."""
    from types import SimpleNamespace

    return SimpleNamespace(
        source=source,
        positions=[
            SimpleNamespace(ticker=t, quantity=q, sector=s) for t, q, s in positions
        ],
    )


def test_resolve_allocation_spreads_a_fund_across_sectors(universe):
    """The decomposition that actually reaches the engines."""
    from app.portfolios.sectors import FUND_SECTOR
    from app.portfolios.service import resolve_allocation

    _, prices, funds = universe
    pf = _fake_portfolio("csv", [("VOO", 10, FUND_SECTOR)])
    resolved = resolve_allocation(pf, prices, funds)

    assert len(resolved.weights) == 11
    assert sum(resolved.weights.values()) == pytest.approx(1.0)
    assert resolved.unmodeled_share == pytest.approx(0.0)
    assert resolved.weights["Information Technology"] > 0.25


def test_resolve_allocation_mixes_fund_and_single_sector(universe):
    """A fund alongside a stock: both contribute, weights still sum to 1."""
    from app.portfolios.sectors import FUND_SECTOR
    from app.portfolios.service import resolve_allocation

    _, prices, funds = universe
    pf = _fake_portfolio(
        "csv",
        [("VOO", 10, FUND_SECTOR), ("XOM", 10, "Energy")],
    )
    resolved = resolve_allocation(pf, prices, funds)
    assert sum(resolved.weights.values()) == pytest.approx(1.0)

    # Energy must exceed the fund's own energy sliver, since XOM adds to it.
    voo_energy = funds["VOO"].sector_weights["Energy"]
    assert resolved.weights["Energy"] > voo_energy


def test_resolve_allocation_renormalizes_over_equity_sleeve(universe):
    """Weights sum to 1.0 over what IS modeled, with the excluded sleeve
    reported separately — engines require weights summing to one."""
    from app.portfolios.sectors import FUND_SECTOR
    from app.portfolios.service import resolve_allocation

    _, prices, funds = universe
    pf = _fake_portfolio("csv", [("AOR", 100, FUND_SECTOR)])
    resolved = resolve_allocation(pf, prices, funds)

    assert sum(resolved.weights.values()) == pytest.approx(1.0)
    assert resolved.unmodeled_share == pytest.approx(0.40)
    assert any("fixed-income" in n for n in resolved.approximations)


def test_unknown_fund_sentinel_is_not_treated_as_a_sector(universe):
    """If a snapshot loses a fund's breakdown, its value must fall into the
    unmodeled bucket — never be attributed to a sector literally named
    '(fund)'."""
    from app.portfolios.sectors import FUND_SECTOR
    from app.portfolios.service import resolve_allocation

    _, prices, _ = universe
    pf = _fake_portfolio(
        "csv", [("VOO", 10, FUND_SECTOR), ("XOM", 10, "Energy")]
    )
    resolved = resolve_allocation(pf, prices, fund_composition={})

    assert FUND_SECTOR not in resolved.weights
    assert resolved.weights == {"Energy": pytest.approx(1.0)}
    assert resolved.unmodeled_share > 0


def test_excluded_bond_fund_counts_toward_unmodeled_share(universe):
    """A portfolio that is heavily bond funds must not report 0% unmodeled
    just because those rows were rejected rather than accepted."""
    csv = b"Symbol,Quantity\nVOO,60\nBND,40\n"
    report = parse_csv(csv, *universe)

    _, prices, _ = universe
    voo_value = 60 * prices["VOO"]
    bnd_value = 40 * prices["BND"]
    expected = bnd_value / (voo_value + bnd_value)

    assert report.totals.unmodeled_share == pytest.approx(expected, abs=1e-4)
    assert report.totals.unmodeled_share > 0.05


def test_sector_etf_is_disclosed_as_a_fund(universe):
    """XLE resolves to Energy either way — the point is that the holder is
    told it is a *fund*.

    It used to sit in the provider's ticker->sector table, so the preview
    returned is_fund=False with no name and no breakdown: a row visually
    indistinguishable from owning a single Energy stock.
    """
    ticker_sector, _, funds = universe
    assert "XLE" not in ticker_sector, "sector ETFs belong in FUND_COMPOSITION"

    report = parse_csv(b"Symbol,Quantity\nXLE,20\n", *universe)
    xle = report.accepted[0]
    assert xle.is_fund
    assert xle.fund_name == "Energy sector fund"
    assert xle.equity_share == 1.0
    assert xle.sector_breakdown == {"Energy": pytest.approx(1.0)}
    assert funds["XLE"].kind == "sector"


def test_sector_etf_resolves_to_exactly_its_own_sector(universe):
    """Routing sector ETFs through decomposition must not move the weight:
    a 100% XLE portfolio is still 100% Energy."""
    from app.portfolios.sectors import FUND_SECTOR
    from app.portfolios.service import resolve_allocation

    _, prices, funds = universe
    pf = _fake_portfolio("csv", [("XLE", 20, FUND_SECTOR)])
    resolved = resolve_allocation(pf, prices, fund_composition=funds)

    assert resolved.weights == {"Energy": pytest.approx(1.0)}
    assert resolved.unmodeled_share == pytest.approx(0.0)


def test_bullion_trust_is_not_an_equity_sector(universe):
    """GLD holds gold, not mining companies.

    It used to be listed under Materials, which handed a commodity's price
    risk to the factor regressions as if it were an equity — and took real
    portfolio weight with it.
    """
    ticker_sector, _, funds = universe
    for t in ("GLD", "SLV"):
        assert t not in ticker_sector

    report = parse_csv(b"Symbol,Quantity\nGLD,24\nSLV,10\n", *universe)
    assert report.accepted == []
    assert {r.reason for r in report.rejected} == {"no_equity_exposure"}
    assert report.totals.unmodeled_share == pytest.approx(1.0)
    assert funds["GLD"].equity_share == 0.0
    assert not funds["GLD"].modelable


def test_no_pooled_vehicle_hides_in_the_sector_table():
    """The two tables must stay disjoint. A ticker in both would resolve by
    whichever lookup ran first, which is how XLE and GLD went undisclosed."""
    from app.snapshots.providers.funds import FUND_COMPOSITION
    from app.snapshots.providers.synthetic import _TICKER_SECTOR

    overlap = set(_TICKER_SECTOR) & set(FUND_COMPOSITION)
    assert overlap == set(), f"tickers in both tables: {sorted(overlap)}"


def test_real_export_holdings_resolve(universe):
    """Holdings from an actual brokerage export that used to be rejected.

    Coverage on a real E*TRADE file sat at 60% because these names were
    simply absent from the universe — nothing was wrong with the parser.
    SPCX is pinned deliberately: SpaceX reads like a technology company, but
    GICS classifies launch under Aerospace & Defense, and filing it under IT
    would misattribute it in exactly the comparison this app exists to show.
    """
    ticker_sector, _, _ = universe
    assert ticker_sector["MRVL"] == "Information Technology"
    assert ticker_sector["ALAB"] == "Information Technology"
    assert ticker_sector["POET"] == "Information Technology"
    assert ticker_sector["SPCX"] == "Industrials"

    csv = b"Symbol,Quantity\nMRVL,19\nALAB,5\nPOET,50\nSPCX,20\n"
    report = parse_csv(csv, *universe)
    assert {a.ticker for a in report.accepted} == {"MRVL", "ALAB", "POET", "SPCX"}
    assert report.rejected == []
    assert report.totals.coverage_pct == 1.0
