"""GET /v1/portfolios/{id}/allocation — the sector mix under the active
snapshot, and what the mix leaves out.

The comparison path resolves the same allocation but keeps only the weights, so
`unmodeled_share` and `approximations` had no way to reach a client. Easy mode
needs them to say which part of the user's money the numbers cover.
"""

from __future__ import annotations

import uuid

from tests.api.conftest import snapshot_sectors

# A 60/40 balanced index fund: 60% maps to equity sectors, the rest is a bond
# sleeve with no sector exposure to model (snapshots/providers/funds.py).
BALANCED_CSV = b"""Symbol,Shares
VBIAX,100
"""


async def test_balanced_fund_reports_its_unmodeled_sleeve(client):
    report = (
        await client.post(
            "/v1/portfolios/preview",
            files={"file": ("holdings.csv", BALANCED_CSV, "text/csv")},
        )
    ).json()
    pf = (
        await client.post(
            "/v1/portfolios",
            json={
                "name": "Balanced",
                "accepted": [
                    {"ticker": a["ticker"], "quantity": a["quantity"]}
                    for a in report["accepted"]
                ],
            },
        )
    ).json()

    r = await client.get(f"/v1/portfolios/{pf['id']}/allocation")
    assert r.status_code == 200, r.text
    alloc = r.json()

    assert alloc["portfolio_id"] == pf["id"]
    assert alloc["snapshot_id"]
    # Weights cover the equity sleeve only, and still sum to 1.0 over it.
    total = sum(w["weight"] for w in alloc["sector_weights"])
    assert abs(total - 1.0) < 1e-6
    # 40% of the value has no sector to attribute it to.
    assert abs(alloc["unmodeled_share"] - 0.40) < 1e-6
    # And the user is told what is being approximated.
    assert alloc["approximations"]


async def test_manual_portfolio_has_nothing_unmodeled(client):
    sectors = snapshot_sectors(client)
    submitted = {sectors[0]: 0.6, sectors[1]: 0.4}
    pf = (
        await client.post(
            "/v1/portfolios",
            json={
                "name": "Manual",
                "sector_weights": [
                    {"sector": s, "weight": w} for s, w in submitted.items()
                ],
            },
        )
    ).json()

    alloc = (await client.get(f"/v1/portfolios/{pf['id']}/allocation")).json()
    assert alloc["unmodeled_share"] == 0.0
    assert alloc["approximations"] == []
    assert {w["sector"]: w["weight"] for w in alloc["sector_weights"]} == submitted
    # Deterministic ordering for a given snapshot.
    returned = [w["sector"] for w in alloc["sector_weights"]]
    assert returned == sorted(returned)


async def test_allocation_matches_the_weights_a_comparison_resolves(client):
    """Both paths must go through the one resolver — otherwise the sleeve notice
    could describe a different allocation than the one the models evaluated."""
    report = (
        await client.post(
            "/v1/portfolios/preview",
            files={"file": ("holdings.csv", BALANCED_CSV, "text/csv")},
        )
    ).json()
    pf = (
        await client.post(
            "/v1/portfolios",
            json={
                "name": "Cross-check",
                "accepted": [
                    {"ticker": a["ticker"], "quantity": a["quantity"]}
                    for a in report["accepted"]
                ],
            },
        )
    ).json()

    alloc = (await client.get(f"/v1/portfolios/{pf['id']}/allocation")).json()
    resource = (
        await client.post(
            "/v1/comparisons",
            json={
                "allocation": {"portfolio_id": pf["id"]},
                "horizon_months": 120,
                "models": ["fama_french"],
            },
        )
    ).json()

    from_allocation = {w["sector"]: w["weight"] for w in alloc["sector_weights"]}
    echoed = {
        w["sector"]: w["weight"]
        for w in resource["request"]["allocation"]["sector_weights"]
    }
    assert from_allocation.keys() == echoed.keys()
    for sector, weight in from_allocation.items():
        assert abs(weight - echoed[sector]) < 1e-9


async def test_unknown_and_foreign_portfolios_404(client):
    r = await client.get(f"/v1/portfolios/{uuid.uuid4()}/allocation")
    assert r.status_code == 404
    assert r.json()["detail"] == "portfolio_not_found"
