"""
Engine registry wiring. Importing this package registers all built-in engines.
Adding model #4: implement the protocol, import + register it here, add a
detail variant to the contract union — nothing else changes.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

from app.contracts.comparison import ModelId

from .base import ENGINE_REGISTRY, RiskModelEngine, register
from .black_litterman import BlackLittermanEngine
from .fama_french import FamaFrenchEngine
from .monte_carlo import MonteCarloEngine


def build_registry(
    pool: ProcessPoolExecutor | None = None,
    provisional_paths: int = 1_000,
    chunk_paths: int = 2_000,
) -> dict[ModelId, RiskModelEngine]:
    """Construct a fresh registry. The Monte Carlo engine needs the shared
    process pool; the parametric engines are stateless."""
    registry: dict[ModelId, RiskModelEngine] = {}
    for engine in (
        FamaFrenchEngine(),
        BlackLittermanEngine(),
        MonteCarloEngine(pool, provisional_paths, chunk_paths),
    ):
        registry[engine.model_id] = engine
    return registry


# Also populate the module-level registry for simple/stateless use (parametric
# engines + a default inline Monte Carlo). The orchestrator builds its own with
# the real process pool.
for _engine in (FamaFrenchEngine(), BlackLittermanEngine(), MonteCarloEngine()):
    register(_engine)


__all__ = [
    "ENGINE_REGISTRY",
    "build_registry",
    "register",
    "FamaFrenchEngine",
    "BlackLittermanEngine",
    "MonteCarloEngine",
]
