"""
In-process LRU for narration, mirroring orchestration/cache.py.

The key embeds the comparison's own cache key, so a comparison reopened from
the durable store after eviction lands on the same entry; and PROMPT_VERSION,
so editing the prompt invalidates every entry rather than serving a mix.

Deliberately not a database column. Narration is cosmetic, the numbers are not,
and a JSONB column would make generated prose part of the 90-day record. The
cost of that choice, stated plainly: there is no durable record of the exact
wording a user was shown, and after a restart the same comparison can be
narrated again with different wording. Spend is bounded by the rate limit, not
by this cache. If an audit trail is ever needed, a narrations table keyed on
(comparison_id, model_id, prompt_version) is the migration.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from app.contracts.comparison import ModelId, RiskLevel

from .prompt import PROMPT_VERSION


def narration_cache_key(
    comparison_cache_key: str, model_id: ModelId, risk_level: RiskLevel
) -> str:
    # risk_level is already inside comparison_cache_key (it is a CompareRequest
    # field); keeping it here is free and makes the key self-documenting.
    payload = "|".join(
        (comparison_cache_key, model_id.value, risk_level.value, PROMPT_VERSION)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class NarrationCache:
    def __init__(self, capacity: int = 256) -> None:
        self._cap = capacity
        self._store: OrderedDict[str, list] = OrderedDict()

    def get(self, key: str) -> list | None:
        value = self._store.get(key)
        if value is not None:
            self._store.move_to_end(key)
        return value

    def put(self, key: str, moves: list) -> None:
        self._store[key] = moves
        self._store.move_to_end(key)
        while len(self._store) > self._cap:
            self._store.popitem(last=False)
