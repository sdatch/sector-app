"""
Per-key sliding-window rate limiter (endpoint spec §8: 10 comparison creations
per minute; cache hits exempt). The key is per-user in v1 (user_model_spec §1.3);
until auth lands (M3) the API passes the client host as the key. Swapping the
key source is the only change M3 makes here.
"""

from __future__ import annotations

from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self._limit = limit
        self._window = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float) -> tuple[bool, float]:
        """Returns (allowed, retry_after_s). Records the hit if allowed."""
        q = self._hits[key]
        cutoff = now - self._window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= self._limit:
            retry_after = q[0] + self._window - now
            return False, max(retry_after, 0.0)
        q.append(now)
        return True, 0.0
