"""
Deterministic cache + idempotency (endpoint spec §7).

Cache key = sha256(snapshot_id + canonical_json(CompareRequest)), where
canonical JSON sorts keys and normalizes float formatting. Because a comparison
is deterministic given its snapshot, an identical request returns the cached
terminal resource with no background work. In-process now; the SQL `comparisons`
table (M3) becomes the durable store and Redis a read-through layer later — the
key is identical across all three, which is the point.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

from app.contracts.comparison import ComparisonResource, CompareRequest


def _canonical(obj) -> str:
    # sort_keys canonicalizes ordering; json's float repr is stable across runs,
    # giving byte-identical strings for equal requests.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def cache_key(snapshot_id: str, request: CompareRequest) -> str:
    payload = snapshot_id + _canonical(request.model_dump(mode="json"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ComparisonCache:
    """LRU of terminal ComparisonResources keyed by cache_key. Only finals are
    cached (PRD D2). Entries lapse naturally on snapshot rotation because the
    key embeds snapshot_id; `clear_snapshot` can also purge eagerly."""

    def __init__(self, capacity: int = 512) -> None:
        self._cap = capacity
        self._store: OrderedDict[str, ComparisonResource] = OrderedDict()

    def get(self, key: str) -> ComparisonResource | None:
        resource = self._store.get(key)
        if resource is not None:
            self._store.move_to_end(key)
        return resource

    def put(self, key: str, resource: ComparisonResource) -> None:
        self._store[key] = resource
        self._store.move_to_end(key)
        while len(self._store) > self._cap:
            self._store.popitem(last=False)


class IdempotencyStore:
    """Maps an Idempotency-Key header to a comparison id so duplicate POSTs
    during creation return the original resource regardless of cache state.
    (24 h retention in the spec; in-process best-effort here.)"""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def put(self, key: str, comparison_id: str) -> None:
        self._store[key] = comparison_id
