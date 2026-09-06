"""
FastAPI application entrypoint.

Surface so far:
  M1 — snapshot warm-up + GET /v1/snapshots/current
  M2 — comparison resource + SSE + orchestration
  M3 — auth (fastapi-users, cookie/JWT, argon2, consent, verification gate),
       Postgres schema, portfolios + CSV ingestion
The app object and lifespan are the stable seam later milestones extend.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.comparisons import router as comparisons_router
from app.auth.schemas import UserCreate, UserRead, UserUpdate
from app.auth.users import ConsentRequired, auth_backend, fastapi_users
from app.config import get_settings
from app.engines import build_registry
from app.history.service import persist_comparison
from app.orchestration.cache import IdempotencyStore
from app.orchestration.comparator import ComparisonManager
from app.orchestration.rate_limit import SlidingWindowLimiter
from app.portfolios.router import router as portfolios_router
from app.progress.router import router as progress_router
from app.scheduler import maintenance_loop
from app.snapshots.artifacts import SnapshotStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    if settings.auto_create_tables:
        # Dev bootstrap; Alembic owns evolution (see migrations/).
        from app.db import models as _models  # noqa: F401 — populate metadata
        from app.db.base import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Snapshot warm-up: build (if absent) + memory-map the active snapshot.
    store = SnapshotStore(settings.artifacts_dir, settings.market_data_provider)
    bundle = store.get(settings.active_snapshot_id)

    executor = ProcessPoolExecutor() if settings.use_process_pool else None
    engines = build_registry(
        pool=executor,
        provisional_paths=settings.mc_provisional_paths,
        chunk_paths=settings.mc_chunk_paths,
    )
    manager = ComparisonManager(
        artifacts=bundle.artifacts,
        ticker_sector=bundle.ticker_sector,
        engines=engines,
        settings=settings,
        on_finalize=persist_comparison,  # durable history (M5)
    )

    app.state.settings = settings
    app.state.snapshots = store
    app.state.manager = manager
    app.state.idempotency = IdempotencyStore()
    app.state.limiter = SlidingWindowLimiter(settings.comparisons_per_minute)

    # Daily maintenance: value portfolios into progress_points + purge expired.
    maintenance = asyncio.create_task(maintenance_loop(bundle, settings))
    try:
        yield
    finally:
        maintenance.cancel()
        if executor is not None:
            executor.shutdown(cancel_futures=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Sector Insight API", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Location", "X-Cache", "Retry-After"],
    )

    @app.exception_handler(ConsentRequired)
    async def _consent_required(request: Request, exc: ConsentRequired):
        # Registration without affirmative consent (PRD FR-7).
        return JSONResponse(status_code=400, content={"detail": "consent_required"})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/snapshots/current")
    async def current_snapshot() -> dict:
        bundle = app.state.snapshots.get(app.state.settings.active_snapshot_id)
        return bundle.artifacts.meta.model_dump(mode="json")

    # --- auth (fastapi-users) ---
    app.include_router(
        fastapi_users.get_auth_router(auth_backend), prefix="/auth", tags=["auth"]
    )
    app.include_router(
        fastapi_users.get_register_router(UserRead, UserCreate),
        prefix="/auth", tags=["auth"],
    )
    app.include_router(
        fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"]
    )
    app.include_router(
        fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"]
    )
    app.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/users", tags=["users"],
    )
    # Dev-only auth helpers (404 in production).
    from app.auth.dev import router as auth_dev_router

    app.include_router(auth_dev_router)

    # --- app resources ---
    app.include_router(portfolios_router)
    app.include_router(comparisons_router)
    app.include_router(progress_router)
    return app


app = create_app()
