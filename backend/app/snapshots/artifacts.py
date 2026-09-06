"""
Artifact persistence + the in-process snapshot store.

Arrays persist to a single .npz per snapshot and are memory-mapped on load, so
warm-up survives process restarts (compute layer design). Scalar/string meta
and the ticker reference tables persist to a sidecar JSON. Market data never
enters SQL (user_model_spec §2.1); this file is that boundary.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from app.contracts.comparison import DataSnapshot
from app.engines.base import SnapshotArtifacts

from .builder import build_artifacts
from .providers.funds import FundComposition
from .providers.synthetic import SyntheticProvider

logger = logging.getLogger(__name__)

_ARRAY_FIELDS = (
    "sector_returns",
    "sector_cov_annual",
    "sector_mu_annual",
    "market_caps",
    "factor_returns",
    "factor_loadings",
    "factor_premia_annual",
    "factor_cov_annual",
    "residual_var",
    "fit_r2",
)


@dataclass(frozen=True)
class SnapshotBundle:
    """Artifacts plus the ingestion reference tables (kept out of the engine-
    facing SnapshotArtifacts because engines never touch tickers)."""

    artifacts: SnapshotArtifacts
    ticker_sector: dict[str, str]
    ticker_price: dict[str, float]
    fund_composition: dict[str, FundComposition] = field(default_factory=dict)

    @property
    def snapshot_id(self) -> str:
        return self.artifacts.meta.snapshot_id


def _npz_path(dir_: Path, snapshot_id: str) -> Path:
    return dir_ / f"{snapshot_id}.npz"


def _meta_path(dir_: Path, snapshot_id: str) -> Path:
    return dir_ / f"{snapshot_id}.meta.json"


def save_bundle(
    bundle: SnapshotBundle, dir_: Path, fingerprint: str | None = None
) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    a = bundle.artifacts
    np.savez(
        _npz_path(dir_, bundle.snapshot_id),
        **{f: getattr(a, f) for f in _ARRAY_FIELDS},
    )
    meta = {
        "snapshot_id": a.meta.snapshot_id,
        "prices_start": a.meta.prices_start.isoformat(),
        "prices_end": a.meta.prices_end.isoformat(),
        "risk_free_rate_annual": a.meta.risk_free_rate_annual,
        "factor_data_vintage": (
            a.meta.factor_data_vintage.isoformat()
            if a.meta.factor_data_vintage
            else None
        ),
        "sectors": list(a.sectors),
        "factor_names": list(a.factor_names),
        "ticker_sector": bundle.ticker_sector,
        "ticker_price": bundle.ticker_price,
        "fund_composition": {
            t: asdict(c) for t, c in bundle.fund_composition.items()
        },
        # Identifies the inputs this artifact was built from, so a later
        # process can tell a current artifact from a stale one.
        "fingerprint": fingerprint,
    }
    _meta_path(dir_, bundle.snapshot_id).write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def load_bundle(snapshot_id: str, dir_: Path) -> SnapshotBundle:
    meta = json.loads(_meta_path(dir_, snapshot_id).read_text(encoding="utf-8"))
    npz = np.load(_npz_path(dir_, snapshot_id), mmap_mode="r")

    snapshot = DataSnapshot(
        snapshot_id=meta["snapshot_id"],
        prices_start=date.fromisoformat(meta["prices_start"]),
        prices_end=date.fromisoformat(meta["prices_end"]),
        risk_free_rate_annual=meta["risk_free_rate_annual"],
        factor_data_vintage=(
            date.fromisoformat(meta["factor_data_vintage"])
            if meta["factor_data_vintage"]
            else None
        ),
    )
    artifacts = SnapshotArtifacts(
        meta=snapshot,
        sectors=tuple(meta["sectors"]),
        factor_names=tuple(meta["factor_names"]),
        risk_free_annual=meta["risk_free_rate_annual"],
        **{f: npz[f] for f in _ARRAY_FIELDS},
    )
    return SnapshotBundle(
        artifacts=artifacts,
        ticker_sector=meta["ticker_sector"],
        ticker_price=meta["ticker_price"],
        fund_composition={
            t: FundComposition(**c)
            for t, c in meta.get("fund_composition", {}).items()
        },
    )


def build_synthetic_bundle(snapshot_id: str) -> SnapshotBundle:
    raw = SyntheticProvider(snapshot_id=snapshot_id).fetch()
    return SnapshotBundle(
        artifacts=build_artifacts(raw),
        ticker_sector=raw.ticker_sector,
        ticker_price=raw.ticker_price,
        fund_composition=raw.fund_composition,
    )


def _persisted_fingerprint(snapshot_id: str, dir_: Path) -> str | None:
    try:
        meta = json.loads(_meta_path(dir_, snapshot_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta.get("fingerprint")


def ensure_bundle(snapshot_id: str, dir_: Path, provider: str = "synthetic") -> SnapshotBundle:
    """Load the snapshot from disk, building + persisting it if absent *or
    stale*. Building is what a daily rotation task does; here it also
    bootstraps a fresh checkout/container with no artifacts volume yet.

    Staleness matters: the artifact carries the ticker reference tables, so an
    environment with an existing volume would otherwise keep serving an old
    ticker universe forever and silently reject holdings the current code
    knows perfectly well.
    """
    if provider != "synthetic":
        if _meta_path(dir_, snapshot_id).exists():
            return load_bundle(snapshot_id, dir_)
        raise NotImplementedError(
            f"Provider '{provider}' not implemented; only 'synthetic' builds "
            "offline. Add a provider under snapshots/providers/."
        )

    expected = SyntheticProvider(snapshot_id=snapshot_id).reference_fingerprint()
    if _meta_path(dir_, snapshot_id).exists():
        if _persisted_fingerprint(snapshot_id, dir_) == expected:
            return load_bundle(snapshot_id, dir_)
        logger.info(
            "snapshot %s artifact is stale (reference data changed) — rebuilding",
            snapshot_id,
        )

    bundle = build_synthetic_bundle(snapshot_id)
    save_bundle(bundle, dir_, fingerprint=expected)
    return bundle


class SnapshotStore:
    """Process-wide cache of loaded snapshots. One active snapshot at a time in
    v1; keyed by id so history/reproduction can pin older snapshots later."""

    def __init__(self, dir_: Path, provider: str = "synthetic") -> None:
        self._dir = dir_
        self._provider = provider
        self._cache: dict[str, SnapshotBundle] = {}

    def get(self, snapshot_id: str) -> SnapshotBundle:
        if snapshot_id not in self._cache:
            self._cache[snapshot_id] = ensure_bundle(
                snapshot_id, self._dir, self._provider
            )
        return self._cache[snapshot_id]
