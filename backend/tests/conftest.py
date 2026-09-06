"""Shared fixtures — a frozen synthetic snapshot bundle for engine tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import numpy as np
import pytest

from app.engines.base import EvaluationContext, OutcomeTransition
from app.engines.context import build_context
from app.snapshots.artifacts import SnapshotBundle, build_synthetic_bundle

FROZEN_SNAPSHOT_ID = "synthetic-test-frozen"


@pytest.fixture(scope="session")
def bundle() -> SnapshotBundle:
    """Deterministic synthetic snapshot, built in-memory (no disk needed)."""
    return build_synthetic_bundle(FROZEN_SNAPSHOT_ID)


@pytest.fixture(scope="session")
def sectors(bundle: SnapshotBundle) -> tuple[str, ...]:
    return bundle.artifacts.sectors


def make_request(models, sectors, *, horizon_months=120, n_sims=8_000, views=None):
    """Build a CompareRequest with an equal-weight allocation over a handful of
    sectors, for use across tests."""
    from app.contracts.comparison import (
        Allocation,
        CompareRequest,
        SectorWeight,
    )

    chosen = sectors[:4]
    w = 1.0 / len(chosen)
    return CompareRequest(
        allocation=Allocation(
            sector_weights=[SectorWeight(sector=s, weight=w) for s in chosen]
        ),
        horizon_months=horizon_months,
        models=list(models),
        n_simulations=n_sims,
        views=views or [],
    )


async def collect(engine, ctx: EvaluationContext) -> list[OutcomeTransition]:
    out: list[OutcomeTransition] = []
    async for t in engine.evaluate(ctx):
        out.append(t)
    return out


def context_for(request, bundle: SnapshotBundle, seed: int = 12345) -> EvaluationContext:
    return build_context(
        request, bundle.artifacts, rng_seed=seed, ticker_sector=bundle.ticker_sector
    )
