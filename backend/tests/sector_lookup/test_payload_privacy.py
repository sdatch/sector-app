"""The privacy boundary: symbols travel, nothing else does."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.sector_lookup import LookupPayload, build_payload


def test_payload_field_set_is_frozen():
    # Adding a field here is a privacy decision; make it one on purpose.
    assert set(LookupPayload.model_fields) == {"tickers"}
    assert LookupPayload.model_config["extra"] == "forbid"


def test_payload_refuses_extra_fields():
    with pytest.raises(ValidationError):
        LookupPayload(tickers=("AAPL",), quantities=(10,))


@pytest.mark.parametrize(
    "bad", ["Pending activity", "ACCT 1234-5678", "", "a" * 20, "AAPL;DROP", "$"]
)
def test_non_symbols_never_enter_a_payload(bad):
    with pytest.raises(ValidationError):
        build_payload([bad])


def test_payload_is_normalized_deduplicated_and_sorted():
    p = build_payload(["msft", "BRK.B", "AAPL", "MSFT"])
    assert p.tickers == ("AAPL", "BRK-B", "MSFT")
