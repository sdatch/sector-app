"""Sector lookup + user-confirmed sectors, end to end, with a fake client.

No network and no API key: `app.state.sector_lookup_client` is the seam, and
the fake records every payload so the privacy guarantee is asserted against
what would really have been sent.
"""

from __future__ import annotations

import json

import httpx

from app.orchestration.rate_limit import SlidingWindowLimiter
from app.sector_lookup.schema import LookupOutput, TickerClassification

CSV = b"""Symbol,Description,Quantity
AAPL,APPLE INC,10
VOO,VANGUARD S&P 500 ETF,5
NEWCO,SOME NEW LISTING,20
Pending activity,,
"""


class FakeLookupClient:
    def __init__(self, answer=None, exc=None):
        self.answer = answer
        self.exc = exc
        self.calls = []

    async def classify(self, payload):
        self.calls.append(payload)
        if self.exc is not None:
            raise self.exc
        return self.answer(payload) if callable(self.answer) else self.answer

    async def aclose(self):
        pass


def industrials(payload):
    return LookupOutput(
        classifications=[
            TickerClassification(
                ticker=t, kind="stock", sector="Industrials", confidence="medium",
                rationale="Makes industrial equipment.", searched=t == "NEWCO",
            )
            for t in payload.tickers
        ]
    )


def enable(client, fake):
    client.app.state.settings.sector_lookup_enabled = True
    client.app.state.sector_lookup_client = fake


async def lookup(client, tickers):
    return await client.post("/v1/portfolios/sector-lookup", json={"tickers": tickers})


async def preview(client, overrides=None):
    data = {"sector_overrides": json.dumps(overrides)} if overrides else None
    return await client.post(
        "/v1/portfolios/preview",
        files={"file": ("h.csv", CSV, "text/csv")},
        data=data,
    )


# --- availability + flag off -------------------------------------------------


async def test_flag_off_is_unavailable_and_never_calls_the_client(client):
    fake = FakeLookupClient(industrials)
    client.app.state.sector_lookup_client = fake  # present but must not be used
    client.app.state.settings.sector_lookup_enabled = False

    r = await client.get("/v1/portfolios/sector-lookup")
    assert r.status_code == 200
    r = await lookup(client, ["AAPL"])
    assert r.status_code == 200
    assert r.json()["source"] == "unavailable"
    assert r.json()["suggestions"] == []
    assert fake.calls == []


async def test_availability_reflects_the_flag(client):
    client.app.state.settings.sector_lookup_enabled = False
    r = (await client.get("/v1/portfolios/sector-lookup")).json()
    assert r["available"] is False
    enable(client, FakeLookupClient(industrials))
    r = (await client.get("/v1/portfolios/sector-lookup")).json()
    assert r == {"available": True, "max_tickers": 100}


async def test_flag_on_without_a_key_is_unavailable(client):
    s = client.app.state.settings
    s.sector_lookup_enabled = True
    s.sector_lookup_stub = False
    s.anthropic_api_key = None
    client.app.state.sector_lookup_client = None
    r = await lookup(client, ["AAPL"])
    assert r.json()["source"] == "unavailable"


# --- happy path + privacy -----------------------------------------------------


async def test_suggestions_come_back_and_only_symbols_are_sent(client):
    fake = FakeLookupClient(industrials)
    enable(client, fake)

    r = await lookup(client, ["NEWCO", "aapl", "Pending activity"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "model"
    assert {s["ticker"] for s in body["suggestions"]} == {"AAPL", "NEWCO"}
    assert body["skipped"] == ["Pending activity"]

    sent = fake.calls[0]
    assert sent.tickers == ("AAPL", "NEWCO")
    blob = sent.model_dump_json()
    assert client.user_email not in blob
    assert "Pending" not in blob  # not ticker-shaped => never sent


async def test_client_error_is_a_200_with_no_suggestions(client):
    enable(client, FakeLookupClient(exc=RuntimeError("boom")))
    r = await lookup(client, ["NEWCO"])
    assert r.status_code == 200
    assert r.json()["source"] == "unavailable"


async def test_too_many_tickers_is_422(client):
    enable(client, FakeLookupClient(industrials))
    client.app.state.settings.sector_lookup_max_tickers = 2
    r = await lookup(client, ["AAA", "BBB", "CCC"])
    assert r.status_code == 422


async def test_rate_limit_applies_to_misses_but_not_cache_hits(client):
    fake = FakeLookupClient(industrials)
    enable(client, fake)
    client.app.state.sector_lookup_limiter = SlidingWindowLimiter(1)

    assert (await lookup(client, ["NEWCO"])).status_code == 200
    # Same symbol again: served from cache, no limiter charge.
    assert (await lookup(client, ["NEWCO"])).status_code == 200
    r = await lookup(client, ["OTHERCO"])
    assert r.status_code == 429
    assert "Retry-After" in r.headers
    assert len(fake.calls) == 1


async def test_csrf_header_required(client):
    enable(client, FakeLookupClient(industrials))
    r = await client.post(
        "/v1/portfolios/sector-lookup",
        json={"tickers": ["AAPL"]},
        headers={"X-Requested-With": ""},
    )
    assert r.status_code == 403


async def test_requires_login(client):
    enable(client, FakeLookupClient(industrials))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client.app),
        base_url="http://test",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as anon:
        r = await anon.post("/v1/portfolios/sector-lookup", json={"tickers": ["A"]})
    assert r.status_code == 401


# --- preview + commit with confirmed sectors ---------------------------------


async def test_preview_marks_unknown_rows_assignable(client):
    r = await preview(client)
    assert r.status_code == 200, r.text
    rej = next(x for x in r.json()["rejected"] if x["reason"] == "unknown_ticker")
    assert rej["ticker"] == "NEWCO"
    assert rej["can_assign_sector"] is True


async def test_preview_with_overrides_admits_and_reweights(client):
    r = await preview(
        client,
        {
            "NEWCO": {"sector": "Industrials", "source": "model"},
            "AAPL": {"sector": "Consumer Discretionary"},
        },
    )
    assert r.status_code == 200, r.text
    accepted = {a["ticker"]: a for a in r.json()["accepted"]}
    assert accepted["NEWCO"]["sector"] == "Industrials"
    assert accepted["NEWCO"]["sector_source"] == "model"
    assert accepted["AAPL"]["sector_source"] == "user"
    assert accepted["VOO"]["sector_source"] == "reference"
    assert abs(sum(a["weight"] for a in accepted.values()) - 1.0) < 1e-4


async def test_preview_refuses_a_fund_override(client):
    r = await preview(client, {"VOO": {"sector": "Energy"}})
    assert r.status_code == 422


async def test_preview_refuses_a_malformed_override(client):
    r = await preview(client, {"NEWCO": {"sector": "Crypto"}})
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_sector_overrides"


async def test_commit_stores_confirmed_sectors_and_they_reach_allocation(client):
    report = (
        await preview(client, {"NEWCO": {"sector": "Industrials", "source": "model"}})
    ).json()
    commit = {
        "name": "With newco",
        "accepted": [
            {
                "ticker": a["ticker"],
                "quantity": a["quantity"],
                **(
                    {"sector": a["sector"], "sector_source": a["sector_source"]}
                    if a["sector_source"] != "reference"
                    else {}
                ),
            }
            for a in report["accepted"]
        ],
    }
    r = await client.post("/v1/portfolios", json=commit)
    assert r.status_code == 201, r.text
    positions = {p["ticker"]: p for p in r.json()["positions"]}
    assert positions["NEWCO"]["sector"] == "Industrials"
    assert positions["NEWCO"]["sector_source"] == "model"
    assert positions["AAPL"]["sector_source"] == "reference"

    alloc = (await client.get(f"/v1/portfolios/{r.json()['id']}/allocation")).json()
    weights = {w["sector"]: w["weight"] for w in alloc["sector_weights"]}
    # NEWCO's value lands in Industrials (VOO contributes some too, so compare
    # against a portfolio without it).
    base = {
        "name": "Without newco",
        "accepted": [
            {"ticker": "AAPL", "quantity": positions["AAPL"]["quantity"]},
            {"ticker": "VOO", "quantity": positions["VOO"]["quantity"]},
        ],
    }
    r2 = await client.post("/v1/portfolios", json=base)
    alloc2 = (await client.get(f"/v1/portfolios/{r2.json()['id']}/allocation")).json()
    weights2 = {w["sector"]: w["weight"] for w in alloc2["sector_weights"]}
    assert weights["Industrials"] > weights2["Industrials"]


async def test_commit_unknown_ticker_without_sector_is_422(client):
    r = await client.post(
        "/v1/portfolios",
        json={"name": "x", "accepted": [{"ticker": "NEWCO", "quantity": 1}]},
    )
    assert r.status_code == 422


async def test_commit_fund_with_sector_is_422(client):
    r = await client.post(
        "/v1/portfolios",
        json={
            "name": "x",
            "accepted": [{"ticker": "VOO", "quantity": 1, "sector": "Energy"}],
        },
    )
    assert r.status_code == 422


async def test_commit_rejects_an_unknown_sector(client):
    r = await client.post(
        "/v1/portfolios",
        json={
            "name": "x",
            "accepted": [{"ticker": "AAPL", "quantity": 1, "sector": "Crypto"}],
        },
    )
    assert r.status_code == 422
