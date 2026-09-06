"""M3 tests — auth gates, CSV ingestion, portfolio management, portfolio_id
comparisons. Exit gate: U1/U2 pass; unverified-user 403; raw file never stored."""

from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import (
    PASSWORD,
    equal_weight_request,
    snapshot_sectors,
)

CSV = b"""Symbol,Shares
AAPL,25
MSFT,10.5
BRK.B,4
Total,39.5
MYPRIVATEFUND,100
JPM,12
"""


# --- U1: registration consent + verification hard gate ----------------------


async def test_registration_requires_consent(client):
    # Reuse the app but register a second user without consent.
    r = await client.post(
        "/auth/register",
        json={"email": "noconsent@example.com", "password": PASSWORD, "consent": False},
    )
    assert r.status_code == 400  # ConsentRequired -> handled as bad request


async def test_unverified_user_blocked_from_comparisons(unverified_client):
    sectors = snapshot_sectors(unverified_client)
    r = await unverified_client.post(
        "/v1/comparisons", json=equal_weight_request(sectors, ["fama_french"])
    )
    assert r.status_code == 403  # verification_required hard gate


async def test_verify_token_flow(unverified_client):
    """The real verification path: fetch the token (dev endpoint), POST it to
    /auth/verify, and confirm the gate lifts. (M3 only exercised a DB flip.)"""
    sectors = snapshot_sectors(unverified_client)
    # Gated before verification.
    r = await unverified_client.post(
        "/v1/comparisons", json=equal_weight_request(sectors, ["fama_french"])
    )
    assert r.status_code == 403

    tok = (await unverified_client.get("/auth/dev/verification-token")).json()
    assert tok["verified"] is False and tok["token"]
    r = await unverified_client.post("/auth/verify", json={"token": tok["token"]})
    assert r.status_code == 200
    assert r.json()["is_verified"] is True

    # Gate lifted.
    r = await unverified_client.post(
        "/v1/comparisons", json=equal_weight_request(sectors, ["fama_french"])
    )
    assert r.status_code == 201


async def test_auth_required(client):
    # A client with no cookie cannot create comparisons.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=client.app),
        base_url="http://test",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as anon:
        sectors = snapshot_sectors(client)
        r = await anon.post(
            "/v1/comparisons", json=equal_weight_request(sectors, ["fama_french"])
        )
        assert r.status_code == 401


async def test_csrf_header_required(client):
    sectors = snapshot_sectors(client)
    r = await client.post(
        "/v1/comparisons",
        json=equal_weight_request(sectors, ["fama_french"]),
        headers={"X-Requested-With": ""},  # strip the CSRF header
    )
    assert r.status_code == 403


# --- U2: CSV preview -> commit ----------------------------------------------


async def test_csv_preview_then_commit(client):
    files = {"file": ("holdings.csv", CSV, "text/csv")}
    r = await client.post("/v1/portfolios/preview", files=files)
    assert r.status_code == 200
    report = r.json()

    accepted = {a["ticker"] for a in report["accepted"]}
    assert {"AAPL", "MSFT", "BRK-B", "JPM"} <= accepted  # BRK.B normalized
    reasons = {rej["reason"] for rej in report["rejected"]}
    assert "unknown_ticker" in reasons  # MYPRIVATEFUND rejected
    assert "ticker_normalized" in reasons  # BRK.B -> BRK-B reported
    assert any("summary" in w for w in report["warnings"])  # Total dropped
    assert report["accepted"][0]["sector"]  # sector resolved

    # Commit only the accepted rows.
    commit = {
        "name": "Brokerage",
        "accepted": [
            {"ticker": a["ticker"], "quantity": a["quantity"]}
            for a in report["accepted"]
        ],
    }
    r = await client.post("/v1/portfolios", json=commit)
    assert r.status_code == 201, r.text
    pf = r.json()
    assert pf["source"] == "csv"
    assert pf["is_default"] is True  # first portfolio becomes default
    stored_tickers = {p["ticker"] for p in pf["positions"]}
    assert "MYPRIVATEFUND" not in stored_tickers


async def test_raw_file_never_stored(client):
    """Only (ticker, quantity, sector) survive ingestion — no raw columns,
    account numbers, or cash lines (NFR-3)."""
    files = {"file": ("holdings.csv", CSV, "text/csv")}
    report = (await client.post("/v1/portfolios/preview", files=files)).json()
    commit = {
        "name": "Privacy",
        "accepted": [
            {"ticker": a["ticker"], "quantity": a["quantity"]}
            for a in report["accepted"]
        ],
    }
    pf = (await client.post("/v1/portfolios", json=commit)).json()
    for p in pf["positions"]:
        assert set(p.keys()) == {"ticker", "quantity", "sector"}


async def test_manual_portfolio_and_default_switch(client):
    sectors = snapshot_sectors(client)
    manual = {
        "name": "Hypothetical",
        "is_default": True,
        "sector_weights": [
            {"sector": sectors[0], "weight": 0.6},
            {"sector": sectors[1], "weight": 0.4},
        ],
    }
    r = await client.post("/v1/portfolios", json=manual)
    assert r.status_code == 201
    assert r.json()["source"] == "manual"

    # Duplicate name -> 409
    r = await client.post("/v1/portfolios", json=manual)
    assert r.status_code == 409

    listing = (await client.get("/v1/portfolios")).json()
    defaults = [p for p in listing if p["is_default"]]
    assert len(defaults) == 1  # exactly one default enforced


async def test_comparison_by_portfolio_id(client):
    sectors = snapshot_sectors(client)
    manual = {
        "name": "PID-test",
        "sector_weights": [
            {"sector": sectors[0], "weight": 0.5},
            {"sector": sectors[2], "weight": 0.5},
        ],
    }
    pf = (await client.post("/v1/portfolios", json=manual)).json()

    body = {
        "allocation": {"portfolio_id": pf["id"]},
        "horizon_months": 120,
        "models": ["fama_french", "black_litterman", "monte_carlo"],
        "n_simulations": 8000,
    }
    r = await client.post("/v1/comparisons", json=body)
    assert r.status_code == 201, r.text
    result = r.json()
    # portfolio_id resolved to explicit sector weights in the echoed request.
    echoed = result["request"]["allocation"]
    assert echoed["portfolio_id"] is None
    assert echoed["sector_weights"] is not None
    got = {w["sector"] for w in echoed["sector_weights"]}
    assert got == {sectors[0], sectors[2]}


async def test_ownership_isolation(client):
    """A second user cannot read the first user's comparison."""
    sectors = snapshot_sectors(client)
    r = await client.post(
        "/v1/comparisons", json=equal_weight_request(sectors, ["fama_french"])
    )
    cid = r.json()["id"]

    # Fresh anonymous client -> new verified user via a second registration.
    from tests.api.conftest import _make_client

    other = await _make_client(client.app, verify=True)
    try:
        r = await other.get(f"/v1/comparisons/{cid}")
        assert r.status_code == 404  # not leaked
    finally:
        await other.aclose()
