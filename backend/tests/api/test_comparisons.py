"""M2 integration tests — comparison endpoints + SSE (endpoint spec §2–8).
Covers user stories U3 (three columns on first paint, MC refines) and U9
(partial failure returned as data, not a transport error)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.contracts.comparison import ModelId
from tests.api.conftest import equal_weight_request, snapshot_sectors

ALL = [ModelId.FAMA_FRENCH, ModelId.BLACK_LITTERMAN, ModelId.MONTE_CARLO]


async def _poll_until_terminal(client, cid, timeout=25.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        r = await client.get(f"/v1/comparisons/{cid}")
        body = r.json()
        if body["status"] != "running":
            return body
        await asyncio.sleep(0.05)
    raise AssertionError("comparison did not terminate in time")


async def test_snapshot_current(client):
    r = await client.get("/v1/snapshots/current")
    assert r.status_code == 200
    assert r.json()["snapshot_id"] == "synthetic-test-api"


async def test_create_returns_three_columns(client):
    sectors = snapshot_sectors(client)
    r = await client.post("/v1/comparisons", json=equal_weight_request(sectors, ALL))
    assert r.status_code == 201
    assert "Location" in r.headers
    body = r.json()
    assert len(body["outcomes"]) == 3  # U3: all three columns on first paint
    by_model = {o["model_id"]: o for o in body["outcomes"]}
    # Closed-form models are complete inline.
    assert by_model["fama_french"]["status"] == "complete"
    assert by_model["black_litterman"]["status"] == "complete"
    # Monte Carlo is running/provisional/complete — never absent.
    assert by_model["monte_carlo"]["status"] in {
        "running", "provisional", "complete"
    }


async def test_progressive_refinement_completes(client):
    sectors = snapshot_sectors(client)
    r = await client.post("/v1/comparisons", json=equal_weight_request(sectors, ALL))
    cid = r.json()["id"]
    final = await _poll_until_terminal(client, cid)
    assert final["status"] == "complete"
    mc = next(o for o in final["outcomes"] if o["model_id"] == "monte_carlo")
    assert mc["status"] == "complete"
    assert mc["outcome"]["distribution"]["p5"] < mc["outcome"]["distribution"]["p95"]
    # provisional badge is gone once complete
    assert "provisional_estimate" not in mc["outcome"]["diagnostics"]["warnings"]


async def test_cache_hit_is_deterministic(client):
    sectors = snapshot_sectors(client)
    req = equal_weight_request(sectors, ALL)
    r1 = await client.post("/v1/comparisons", json=req)
    cid = r1.json()["id"]
    final1 = await _poll_until_terminal(client, cid)

    r2 = await client.post("/v1/comparisons", json=req)
    assert r2.status_code == 200
    assert r2.headers.get("X-Cache") == "hit"
    final2 = r2.json()
    # Bit-identical outcomes (NFR-2 determinism) — compare model metrics.
    def metrics(b):
        return {o["model_id"]: o["outcome"]["metrics"] for o in b["outcomes"]}
    assert metrics(final1) == metrics(final2)


async def test_partial_failure_is_data(client):
    """U9: a BL view on an unknown sector fails only that column; FF + MC still
    return, HTTP is still 201, aggregate is partial."""
    sectors = snapshot_sectors(client)
    req = equal_weight_request(
        sectors, ALL,
        views=[{
            "sector": "Cryptomining",
            "expected_annual_return": 0.2,
            "confidence": 0.6,
        }],
    )
    r = await client.post("/v1/comparisons", json=req)
    assert r.status_code == 201
    final = await _poll_until_terminal(client, r.json()["id"])
    assert final["status"] == "partial"
    by_model = {o["model_id"]: o for o in final["outcomes"]}
    assert by_model["black_litterman"]["status"] == "failed"
    assert by_model["black_litterman"]["error"]["code"] == "unknown_sector"
    assert by_model["black_litterman"]["error"]["retryable"] is False
    assert by_model["fama_french"]["status"] == "complete"
    assert by_model["monte_carlo"]["status"] == "complete"
    # user-facing caveat surfaced in normalization_notes
    assert any("Cryptomining" in n for n in final["normalization_notes"])


async def test_invalid_requests(client):
    sectors = snapshot_sectors(client)
    # weights don't sum to 1 -> contract 422
    bad = equal_weight_request(sectors, ALL)
    bad["allocation"]["sector_weights"][0]["weight"] = 0.9
    r = await client.post("/v1/comparisons", json=bad)
    assert r.status_code == 422

    # unknown sector -> allocation 422
    unknown = {
        "allocation": {"sector_weights": [{"sector": "Nonesuch", "weight": 1.0}]},
        "horizon_months": 60,
        "models": ["fama_french"],
    }
    r = await client.post("/v1/comparisons", json=unknown)
    assert r.status_code == 422

    # portfolio_id referencing a non-existent portfolio -> 404
    pid = {
        "allocation": {"portfolio_id": "00000000-0000-0000-0000-000000000001"},
        "horizon_months": 60,
        "models": ["fama_french"],
    }
    r = await client.post("/v1/comparisons", json=pid)
    assert r.status_code == 404


async def test_sse_streams_to_terminal(client):
    sectors = snapshot_sectors(client)
    r = await client.post(
        "/v1/comparisons",
        json=equal_weight_request(sectors, ALL, n_simulations=20000),
    )
    cid = r.json()["id"]

    events = []
    async with client.stream("GET", f"/v1/comparisons/{cid}/events") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        cur = {}
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                cur["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                cur["data"] = line.split(":", 1)[1].strip()
            elif line == "":
                if cur:
                    events.append(cur)
                    if cur.get("event") == "comparison":
                        break
                    cur = {}

    types = [e["event"] for e in events]
    assert "comparison" in types  # terminal event closes the stream
    terminal = json.loads(events[-1]["data"])
    assert terminal["status"] in {"complete", "partial", "failed"}


async def test_sse_terminal_replay_on_late_subscribe(client):
    sectors = snapshot_sectors(client)
    r = await client.post("/v1/comparisons", json=equal_weight_request(sectors, ALL))
    cid = r.json()["id"]
    await _poll_until_terminal(client, cid)

    # Subscribing after terminal replays the terminal comparison event + closes.
    saw_comparison = False
    async with client.stream("GET", f"/v1/comparisons/{cid}/events") as resp:
        async for line in resp.aiter_lines():
            if line.startswith("event: comparison"):
                saw_comparison = True
    assert saw_comparison


async def test_get_unknown_404(client):
    r = await client.get("/v1/comparisons/00000000-0000-0000-0000-000000000009")
    assert r.status_code == 404
