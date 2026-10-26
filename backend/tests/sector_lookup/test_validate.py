"""The honesty boundary: each classification is checked on its own."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.sector_lookup import build_payload
from app.sector_lookup.schema import LookupOutput, TickerClassification
from app.sector_lookup.validate import validate_output


def _c(ticker, kind="stock", sector="Industrials", **kw):
    return TickerClassification(
        ticker=ticker,
        kind=kind,
        sector=sector,
        confidence=kw.get("confidence", "high"),
        rationale=kw.get("rationale", "Makes things."),
        searched=kw.get("searched", False),
        company_name=kw.get("company_name"),
    )


def _out(*cs):
    return LookupOutput(classifications=list(cs))


def test_valid_entries_pass():
    out = validate_output(
        _out(_c("AAA"), _c("BBB", kind="fund", sector=None)),
        build_payload(["AAA", "BBB"]),
    )
    assert out["AAA"].sector == "Industrials"
    assert out["BBB"].kind == "fund" and out["BBB"].sector is None


def test_none_is_nothing_checked():
    assert validate_output(None, build_payload(["AAA"])) == {}


def test_unrequested_ticker_is_dropped():
    assert validate_output(_out(_c("ZZZ")), build_payload(["AAA"])) == {}


def test_fund_with_a_sector_is_dropped():
    """Invariant 8 again, at the model boundary."""
    out = validate_output(
        _out(_c("AAA", kind="fund", sector="Energy")), build_payload(["AAA"])
    )
    assert out == {}


def test_stock_without_a_sector_is_dropped():
    assert validate_output(_out(_c("AAA", sector=None)), build_payload(["AAA"])) == {}


def test_empty_rationale_is_dropped():
    assert validate_output(_out(_c("AAA", rationale="  ")), build_payload(["AAA"])) == {}


def test_duplicate_answers_are_both_distrusted():
    out = validate_output(
        _out(_c("AAA"), _c("AAA", sector="Energy"), _c("BBB")),
        build_payload(["AAA", "BBB"]),
    )
    assert set(out) == {"BBB"}


def test_one_bad_entry_does_not_sink_the_batch():
    out = validate_output(
        _out(_c("AAA", sector=None), _c("BBB")), build_payload(["AAA", "BBB"])
    )
    assert set(out) == {"BBB"}


def test_returned_ticker_is_normalized():
    out = validate_output(_out(_c("brk.b")), build_payload(["BRK-B"]))
    assert set(out) == {"BRK-B"}


def test_long_text_is_clipped():
    out = validate_output(
        _out(_c("AAA", rationale="x" * 1000, company_name="y" * 500)),
        build_payload(["AAA"]),
    )
    assert len(out["AAA"].rationale) == 300
    assert len(out["AAA"].company_name) == 120


def test_schema_refuses_a_foreign_sector():
    with pytest.raises(ValidationError):
        _c("AAA", sector="Crypto")
