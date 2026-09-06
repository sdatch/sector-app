"""Async HTTP client bound to a fresh app (lifespan run) with a registered,
verified, logged-in user. Uses an isolated SQLite DB + temp artifacts dir so no
Postgres is needed for tests.

Env is set at import time (before app modules bind the engine/settings)."""

from __future__ import annotations

import os
import tempfile
import uuid

_TMP = tempfile.mkdtemp(prefix="sector-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP}/test.db")
os.environ.setdefault("ARTIFACTS_DIR", f"{_TMP}/artifacts")
os.environ.setdefault("COMPARISONS_PER_MINUTE", "1000")
os.environ.setdefault("ACTIVE_SNAPSHOT_ID", "synthetic-test-api")
os.environ.setdefault("JWT_SECRET", "test-secret-key-at-least-32-bytes-long-xx")
# No background maintenance loop in tests — it contends with test requests on
# the single-writer SQLite DB. Progress is exercised directly via portfolio
# creation + the M5 unit tests.
os.environ.setdefault("RUN_MAINTENANCE_ON_STARTUP", "false")

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import update  # noqa: E402

PASSWORD = "sTrong-pass-123"


async def _set_verified(email: str) -> None:
    from app.db.base import async_session_maker
    from app.db.models import User

    async with async_session_maker() as s:
        await s.execute(
            update(User).where(User.email == email).values(is_verified=True)
        )
        await s.commit()


async def _bootstrap_app():
    from app.config import get_settings

    get_settings.cache_clear()
    import app.db.models  # noqa: F401
    from app.db.base import Base, engine
    from app.main import create_app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return create_app()


async def _register_login(c: httpx.AsyncClient, verify: bool) -> str:
    email = f"u{uuid.uuid4().hex[:12]}@example.com"
    r = await c.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "consent": True},
    )
    assert r.status_code == 201, r.text
    if verify:
        await _set_verified(email)
    r = await c.post("/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code in (200, 204), r.text
    return email


async def _make_client(app, verify: bool) -> httpx.AsyncClient:
    """Return an opened, registered+logged-in client. Caller must aclose()."""
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    await c.__aenter__()
    c.app = app
    c.user_email = await _register_login(c, verify)
    return c


@pytest.fixture
async def client():
    app = await _bootstrap_app()
    async with app.router.lifespan_context(app):
        c = await _make_client(app, verify=True)
        try:
            yield c
        finally:
            await c.aclose()


@pytest.fixture
async def unverified_client():
    app = await _bootstrap_app()
    async with app.router.lifespan_context(app):
        c = await _make_client(app, verify=False)
        try:
            yield c
        finally:
            await c.aclose()


def equal_weight_request(sectors, models, **kw):
    chosen = sectors[:4]
    w = round(1.0 / len(chosen), 6)
    weights = [{"sector": s, "weight": w} for s in chosen]
    weights[-1]["weight"] = round(1.0 - w * (len(chosen) - 1), 6)
    body = {
        "allocation": {"sector_weights": weights},
        "horizon_months": kw.get("horizon_months", 120),
        "models": [m.value if hasattr(m, "value") else m for m in models],
        "n_simulations": kw.get("n_simulations", 8000),
    }
    if "views" in kw:
        body["views"] = kw["views"]
    return body


def snapshot_sectors(client):
    return client.app.state.snapshots.get(
        client.app.state.settings.active_snapshot_id
    ).artifacts.sectors
