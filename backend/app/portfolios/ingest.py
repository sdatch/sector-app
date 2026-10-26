"""
CSV portfolio ingestion (user_model_spec §3). Parse in memory, return an
IngestReport, persist NOTHING. Only validated (ticker, quantity, sector) survive
a later commit; the raw file — account numbers, names, cash lines — never
touches disk.

Header-tolerant: broker exports vary, so a mapping table normalizes column
names before validation, and the header is located anywhere in a leading
preamble (account lines, blanks, disclaimers) rather than assumed on row 1.
Unknown columns are ignored; summary lines reported as skipped; tickers outside
the snapshot universe rejected (they cannot be risk-modeled and admitting them
would silently corrupt attribution). Funds are recognized and decomposed into
the sectors they hold; the ones with no equity sleeve at all (bond funds,
commodity trusts) are rejected under their own reason, so the UI can explain
*why* rather than calling a household ETF unknown.

Every row keeps its true file line number so the preview can play the file back
to the user in its own order, included and excluded rows interleaved.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable

from app.snapshots.providers.funds import FundComposition

from .schemas import (
    IngestAccepted,
    IngestRejected,
    IngestReport,
    IngestTotals,
    SectorOverride,
)
from .sectors import FUND_SECTOR

MAX_BYTES = 1_000_000  # 1 MB
MAX_ROWS = 500
NOMINAL_VALUE = 100_000.0  # weight-mode notional base

_HEADER_MAP = {
    "ticker": "ticker", "symbol": "ticker", "sym": "ticker",
    "quantity": "quantity", "shares": "quantity", "qty": "quantity",
    "units": "quantity",
    "weight": "weight", "allocation": "weight", "pct": "weight",
}
_SUMMARY_TICKERS = {
    "total", "totals", "subtotal", "grand total", "account total", "",
    "cash", "cash & cash investments", "cash and equivalents", "money market",
    "pending activity", "settled cash",
}

# Rows to look at when hunting for the header. Broker exports routinely lead
# with an account line, a blank, and a disclaimer before the real header.
_HEADER_SCAN_ROWS = 12

# Pooled vehicles are recognized from the snapshot's fund_composition table and
# decomposed across the sectors they hold (see snapshots/providers/funds.py).
# Only a fund with no modelable equity exposure at all — a pure bond fund — is
# rejected, and then under its own reason so the UI can explain why.


class IngestError(ValueError):
    """Fatal ingestion problem (size/format) — maps to HTTP 422."""


def _decode(content: bytes) -> str:
    if len(content) > MAX_BYTES:
        raise IngestError(f"File exceeds {MAX_BYTES // 1000} KB limit")
    for encoding in ("utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("File is not valid UTF-8 or Latin-1 text")


def _normalize_ticker(raw: str) -> tuple[str, bool]:
    """Uppercase/trim; broker '.' class shares (BRK.B) -> hyphen (BRK-B).
    Returns (normalized, was_changed)."""
    t = raw.strip().upper()
    norm = t.replace(".", "-")
    return norm, norm != t


def _map_headers(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for i, col in enumerate(header):
        # Strip BOM, quotes and stray whitespace brokers leave in headers.
        key = _HEADER_MAP.get(col.strip().strip('"\'').lstrip("﻿").lower())
        if key and key not in mapping:
            mapping[key] = i
    return mapping


def _find_header(
    rows: list[tuple[int, list[str]]],
) -> tuple[dict[str, int], int] | None:
    """Locate the header row, tolerating a preamble.

    Broker exports commonly open with an account name, a blank line, or a
    disclaimer before the real header, so scanning only row 0 would fall back
    to positional parsing and reject nearly every position. Returns
    (column map, index of the header row) or None if no header is present.
    """
    for i, (_line, row) in enumerate(rows[:_HEADER_SCAN_ROWS]):
        cols = _map_headers(row)
        # A header needs the ticker column plus something to size the position.
        if "ticker" in cols and ("quantity" in cols or "weight" in cols):
            return cols, i
    return None


def parse_csv(
    content: bytes,
    ticker_sector: dict[str, str],
    ticker_price: dict[str, float],
    fund_composition: dict[str, FundComposition] | None = None,
    *,
    price_of: Callable[[str], float | None] | None = None,
    sector_overrides: dict[str, SectorOverride] | None = None,
) -> IngestReport:
    """Parse a broker export into accepted and rejected rows.

    `sector_overrides` carries sectors the user confirmed in the preview
    (ticker -> sector). An override admits a ticker the reference table does
    not know, or replaces the table's sector for one it does; it never applies
    to a fund, whose exposure comes from its holdings (invariant 8). With no
    overrides the report is exactly what it was before overrides existed.

    `price_of` values a ticker, listed or not (SnapshotBundle.price_of);
    without it only the reference prices are used.
    """
    funds = fund_composition or {}
    overrides = sector_overrides or {}
    price_of = price_of or ticker_price.get
    text = _decode(content)
    reader = csv.reader(io.StringIO(text))
    # Carry each row's true 1-based file line number so the preview UI can
    # point the user at the actual line in their file; blank rows are skipped
    # for parsing but must not shift the numbering.
    rows = [(i, r) for i, r in enumerate(reader, start=1) if any(c.strip() for c in r)]
    if not rows:
        raise IngestError("File contains no data rows")

    # Detect a header row anywhere in the preamble; else assume canonical
    # [ticker, quantity] positional layout over every row.
    found = _find_header(rows)
    if found is not None:
        cols, header_idx = found
        data_rows = rows[header_idx + 1 :]
    else:
        cols = {"ticker": 0, "quantity": 1}
        data_rows = rows

    if len(data_rows) > MAX_ROWS:
        raise IngestError(f"File exceeds {MAX_ROWS} data rows")

    use_weight = "weight" in cols and "quantity" not in cols

    accepted: list[IngestAccepted] = []
    rejected: list[IngestRejected] = []
    summary_dropped = 0
    # Provisional (line, ticker, sector, numeric, note) tuples before
    # weight/value resolution.
    staged: list[tuple[int, str, str, float, str | None]] = []
    # line -> where an overridden row's sector came from.
    sources: dict[int, str] = {}
    # Priceable holdings we recognize but cannot model at all (bond funds).
    # Kept so the "unmodeled share" reflects them instead of pretending an
    # account that is 40% bonds is fully covered.
    excluded_funds: list[tuple[str, float]] = []

    for line_no, row in data_rows:
        raw = ",".join(row)
        t_idx = cols["ticker"]
        num_idx = cols["weight"] if use_weight else cols.get("quantity", 1)
        if t_idx >= len(row):
            rejected.append(IngestRejected(row=line_no, raw=raw, reason="malformed_row"))
            continue

        raw_ticker = row[t_idx].strip()
        if raw_ticker.lower() in _SUMMARY_TICKERS:
            summary_dropped += 1
            rejected.append(
                IngestRejected(
                    row=line_no, raw=raw, reason="summary_line",
                    # No resolution. The UI renders "<label> — <resolution>",
                    # and the label already reads "Summary line — not a
                    # position"; anything here just repeats it back.
                    resolution=None,
                )
            )
            continue

        ticker, changed = _normalize_ticker(raw_ticker)
        resolution = f"{raw_ticker} → {ticker}" if changed else None

        if num_idx >= len(row) or not row[num_idx].strip():
            rejected.append(IngestRejected(row=line_no, raw=raw, reason="missing_quantity"))
            continue
        try:
            amount = float(
                row[num_idx].replace(",", "").replace("$", "").replace("%", "").strip()
            )
        except ValueError:
            rejected.append(IngestRejected(row=line_no, raw=raw, reason="invalid_number"))
            continue
        if amount <= 0:
            rejected.append(IngestRejected(row=line_no, raw=raw, reason="non_positive"))
            continue

        override = overrides.get(ticker)
        if override is not None and ticker in funds:
            raise IngestError(
                f"{ticker} is a fund: its sectors come from its holdings and "
                "cannot be set by hand"
            )
        if override is not None and override.sector != ticker_sector.get(ticker):
            if price_of(ticker) is None:
                rejected.append(
                    IngestRejected(
                        row=line_no, raw=raw, reason="no_price", ticker=ticker
                    )
                )
                continue
            staged.append((line_no, ticker, override.sector, amount, resolution))
            sources[line_no] = override.source
            if changed:
                rejected.append(
                    IngestRejected(
                        row=line_no, raw=raw, reason="ticker_normalized",
                        resolution=f"{ticker} accepted",
                    )
                )
            continue

        sector = ticker_sector.get(ticker)
        if sector is None:
            comp = funds.get(ticker)
            if comp is not None and comp.modelable:
                # A pooled vehicle: accepted, and spread across the sectors it
                # actually holds rather than forced into one.
                staged.append((line_no, ticker, FUND_SECTOR, amount, resolution))
                continue
            if comp is not None:
                # Recognized, but nothing to model — a pure bond fund has no
                # equity sector exposure at all. Priceable, so its value still
                # counts toward "how much of this account is unmodeled".
                excluded_funds.append((ticker, amount))
                rejected.append(
                    IngestRejected(
                        row=line_no,
                        raw=raw,
                        reason="no_equity_exposure",
                        # Just the name: the reason label supplies "no
                        # equity sector exposure to model", so repeating it
                        # here renders the phrase twice in one cell.
                        resolution=comp.name,
                    )
                )
                continue
            rejected.append(
                IngestRejected(
                    row=line_no, raw=raw, reason="unknown_ticker",
                    resolution=resolution,
                    ticker=ticker,
                    can_assign_sector=price_of(ticker) is not None,
                )
            )
            continue

        staged.append((line_no, ticker, sector, amount, resolution))
        if changed:
            rejected.append(
                IngestRejected(
                    row=line_no, raw=raw, reason="ticker_normalized",
                    resolution=f"{ticker} accepted",
                )
            )

    # Resolve staged rows to quantities + weights. Excluded-but-priceable
    # funds count toward the weight total: they are part of the account even
    # though they cannot be modeled.
    if use_weight:
        total_w = sum(a for *_, a, _ in staged) + sum(a for _, a in excluded_funds)
        if staged and abs(total_w - 1.0) > 1e-4:
            raise IngestError(
                f"weight column present but weights sum to {total_w:.4f}, not 1.0"
            )

    values: list[float] = []
    for _line, ticker, _sector, amount, _res in staged:
        price = price_of(ticker)
        qty = (amount * NOMINAL_VALUE / price) if use_weight else amount
        values.append(qty * price)
    total_value = sum(values) or 1.0

    unmodeled_value = 0.0
    for (line_no, ticker, sector, amount, res), value in zip(staged, values):
        price = price_of(ticker)
        qty = (amount * NOMINAL_VALUE / price) if use_weight else amount
        comp = funds.get(ticker) if sector == FUND_SECTOR else None
        if comp is not None:
            unmodeled_value += value * (1.0 - comp.equity_share)
        accepted.append(
            IngestAccepted(
                ticker=ticker,
                quantity=round(qty, 6),
                sector=sector,
                last_price=price,
                value=round(value, 2),
                weight=round(value / total_value, 6),
                row=line_no,
                note=res or (comp.approximation if comp else None),
                is_fund=comp is not None,
                fund_name=comp.name if comp else None,
                equity_share=comp.equity_share if comp else 1.0,
                sector_breakdown=dict(comp.sector_weights) if comp else None,
                sector_source=sources.get(line_no, "reference"),
            )
        )

    # Value the recognized-but-unmodelable funds on the same basis, then state
    # the unmodeled share over the whole priceable account rather than over the
    # accepted rows alone — otherwise a portfolio that is 40% bond funds
    # reports 0% unmodeled, which is exactly backwards.
    excluded_value = 0.0
    for ticker, amount in excluded_funds:
        price = price_of(ticker) or 0.0
        qty = (amount * NOMINAL_VALUE / price) if (use_weight and price) else amount
        excluded_value += qty * price
    unmodeled_value += excluded_value
    priceable_total = sum(values) + excluded_value
    unmodeled_share = (
        unmodeled_value / priceable_total if priceable_total > 0 else 0.0
    )

    warnings: list[str] = []
    if summary_dropped:
        warnings.append(f"{summary_dropped} rows dropped as summary lines")
    if use_weight:
        warnings.append("weights converted to notional quantities vs $100k base")

    n_unknown = sum(r.reason == "unknown_ticker" for r in rejected)
    n_assignable = sum(r.can_assign_sector for r in rejected)
    n_overridden = sum(a.sector_source != "reference" for a in accepted)
    n_no_equity = sum(r.reason == "no_equity_exposure" for r in rejected)
    n_decomposed = sum(a.is_fund for a in accepted)
    if n_unknown:
        warnings.append(
            f"{n_unknown} holding{'' if n_unknown == 1 else 's'} outside the "
            "snapshot's ticker universe could not be risk-modeled"
            + (" — choose a sector to include it" if n_assignable == 1 else
               " — choose a sector for each to include them" if n_assignable
               else "")
        )
    if n_overridden:
        one = n_overridden == 1
        warnings.append(
            f"{n_overridden} holding{'' if one else 's'} use{'s' if one else ''} "
            "a sector you confirmed rather than the reference table's"
        )
    if n_no_equity:
        warnings.append(
            f"{n_no_equity} holding{'' if n_no_equity == 1 else 's'} excluded — "
            "bond funds and commodity trusts carry no equity sector exposure "
            "to model"
        )
    if n_decomposed:
        one = n_decomposed == 1
        warnings.append(
            f"{n_decomposed} fund{'' if one else 's'} decomposed into the "
            f"sectors {'it holds' if one else 'they hold'}, using typical "
            "published allocations"
        )
    for note in dict.fromkeys(
        a.note for a in accepted if a.is_fund and a.note
    ):
        warnings.append(note)

    considered = len(accepted) + sum(
        r.reason
        in {
            "unknown_ticker", "no_price", "no_equity_exposure", "invalid_number",
            "non_positive",
        }
        for r in rejected
    )
    coverage = round(len(accepted) / considered, 4) if considered else 0.0

    return IngestReport(
        accepted=accepted,
        rejected=rejected,
        warnings=warnings,
        totals=IngestTotals(
            value=round(sum(values), 2),
            positions=len(accepted),
            coverage_pct=coverage,
            unmodeled_share=round(unmodeled_share, 4),
        ),
    )
