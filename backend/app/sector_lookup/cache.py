"""
Per-ticker in-process LRU.

A classification is reference data about a company, not about anyone's
portfolio, so one user's lookup answers the next user's identical question for
free — and the cache stores no user or portfolio at all, only symbol ->
suggestion. Keyed with the model and PROMPT_VERSION so changing either starts
clean. In-process on purpose: market and reference data stay out of SQL
(invariant 5), and the stored *portfolio* sector — the only one that matters —
is already durable once the user confirms it.
"""

from __future__ import annotations

from collections import OrderedDict

from .prompt import PROMPT_VERSION
from .validate import SectorSuggestion


def lookup_cache_key(ticker: str, model: str) -> str:
    return f"{PROMPT_VERSION}|{model}|{ticker}"


class SectorLookupCache:
    def __init__(self, capacity: int = 2048) -> None:
        self._cap = capacity
        self._store: OrderedDict[str, SectorSuggestion] = OrderedDict()

    def get(self, key: str) -> SectorSuggestion | None:
        value = self._store.get(key)
        if value is not None:
            self._store.move_to_end(key)
        return value

    def put(self, key: str, value: SectorSuggestion) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self._cap:
            self._store.popitem(last=False)
