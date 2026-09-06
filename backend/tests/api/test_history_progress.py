"""M5 tests — comparison persistence + history (U8), progress (U7), 90-day
purge. Exit gate: U7/U8 pass; purge verified against seeded expired rows."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.contracts.comparison import ModelId
from tests.api.conftest import equal_weight_request, snapshot_sectors

ALL = [ModelId.FAMA_FRENCH, ModelId.BLACK_LITTERMAN, ModelId.MONTE_CARLO]


async def _me_id(client) -> uuid.UUID:
    return uuid.UUID((await client.get("/users/me")).json()["id"])


async def test_comparison_persisted_and_reopenable(client):
    sectors = snapshot_sectors(client)
    r = await client.post("/v1/comparisons", json=equal_weight_request(sectors, ALL))
    cid = r.json()["id"]

    # Wait for terminal + background persistence.
    for _ in range(100):
        body = (await client.get(f"/v1/comparisons/{cid}")).json()
        if body["status"] != "running":
            break
        await asyncio.sleep(0.05)

    # History list (U8) — poll until the finalize task has written the row.
    history = []
    for _ in range(40):
        history = (await client.get("/v1/comparisons")).json()
        if any(h["id"] == cid for h in history):
            break
        await asyncio.sleep(0.05)
    assert any(h["id"] == cid for h in history)
    entry = next(h for h in history if h["id"] == cid)
    assert entry["status"] in {"complete", "partial"}
    assert set(entry["models"]) == {m.value for m in ALL}

    # Reopen returns the full resource.
    full = (await client.get(f"/v1/comparisons/{cid}")).json()
    assert len(full["outcomes"]) == 3


async def test_progress_trajectory(client):
    sectors = snapshot_sectors(client)
    manual = {
        "name": "Progress-test",
        "sector_weights": [
            {"sector": sectors[0], "weight": 0.5},
            {"sector": sectors[1], "weight": 0.5},
        ],
    }
    pf = (await client.post("/v1/portfolios", json=manual)).json()

    series = (await client.get("/v1/progress")).json()
    mine = next((s for s in series if s["portfolio_id"] == pf["id"]), None)
    assert mine is not None, "portfolio should have a seeded trajectory"
    assert len(mine["points"]) > 10  # a real multi-day trajectory
    pts = mine["points"]
    assert pts[0]["as_of"] < pts[-1]["as_of"]  # chronological
    assert all(p["total_value"] > 0 for p in pts)
    assert pts[-1]["volatility"] is not None


async def test_purge_expired_comparisons(client):
    from app.db.base import async_session_maker
    from app.db.models import Comparison
    from app.history.service import purge_expired

    user_id = await _me_id(client)
    now = datetime.now(timezone.utc)
    expired_id = uuid.uuid4()

    async with async_session_maker() as s:
        s.add(
            Comparison(
                id=expired_id,
                user_id=user_id,
                portfolio_id=None,
                snapshot_id="synthetic-test-api",
                request={"models": ["fama_french"]},
                result={"status": "complete"},
                status="complete",
                cache_key="seed-expired",
                created_at=now - timedelta(days=120),
                expires_at=now - timedelta(days=30),  # already lapsed
            )
        )
        await s.commit()

    # Expired rows are excluded from history immediately (cache lookups filter).
    history = (await client.get("/v1/comparisons")).json()
    assert not any(h["id"] == str(expired_id) for h in history)

    # And the purge task hard-deletes them.
    async with async_session_maker() as s:
        purged = await purge_expired(s, datetime.now(timezone.utc))
    assert purged >= 1

    async with async_session_maker() as s:
        from sqlalchemy import select

        remaining = (
            await s.execute(select(Comparison).where(Comparison.id == expired_id))
        ).scalar_one_or_none()
    assert remaining is None
