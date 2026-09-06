"""
Daily maintenance (PRD FR-5/FR-6). On snapshot rotation the same task values
every portfolio into progress_points and purges comparisons past their 90-day
expiry. Single-process asyncio loop for v1; moves to a real scheduler / worker
when replicas arrive — the functions are the unit of work either way.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import Settings
from app.db.base import async_session_maker
from app.history.service import purge_expired
from app.progress.service import run_progress_for_all
from app.snapshots.artifacts import SnapshotBundle


async def run_maintenance(bundle: SnapshotBundle) -> dict:
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        purged = await purge_expired(session, now)
        points = await run_progress_for_all(session, bundle)
    return {"purged": purged, "progress_points": points}


async def maintenance_loop(bundle: SnapshotBundle, settings: Settings) -> None:
    if settings.run_maintenance_on_startup:
        try:
            await run_maintenance(bundle)
        except Exception:  # noqa: BLE001 — never let maintenance kill startup
            pass
    while True:
        await asyncio.sleep(settings.maintenance_interval_s)
        try:
            await run_maintenance(bundle)
        except Exception:  # noqa: BLE001
            pass
