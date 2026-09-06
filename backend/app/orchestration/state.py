"""
Comparison state — the observable resource plus the machinery to snapshot it.
In-process for single-worker v1; the SQL `comparisons` row (M3) is the durable
form of exactly this data.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.contracts.comparison import (
    ComparisonResource,
    ComparisonStatus,
    CompareRequest,
    DataSnapshot,
    ModelId,
    OutcomeEnvelope,
    OutcomeStatus,
)

_UNRESOLVED = {OutcomeStatus.PENDING, OutcomeStatus.RUNNING, OutcomeStatus.PROVISIONAL}


@dataclass
class ComparisonState:
    id: UUID
    request: CompareRequest
    snapshot: DataSnapshot
    cache_key: str
    generated_at: datetime
    envelopes: dict[ModelId, OutcomeEnvelope]
    user_id: str | None = None  # owner; comparisons are user-scoped (v1)
    portfolio_id: str | None = None  # source portfolio when allocation resolved
    normalization_notes: list[str] = field(default_factory=list)
    terminal_event: asyncio.Event = field(default_factory=asyncio.Event)
    # loop-time of the last emitted progress event, per model (2/s throttle)
    last_progress_at: dict[ModelId, float] = field(default_factory=dict)

    @property
    def aggregate_status(self) -> ComparisonStatus:
        statuses = [e.status for e in self.envelopes.values()]
        if any(s in _UNRESOLVED for s in statuses):
            return ComparisonStatus.RUNNING
        # all terminal now
        completed = sum(s is OutcomeStatus.COMPLETE for s in statuses)
        failed = sum(s is OutcomeStatus.FAILED for s in statuses)
        if failed == 0:
            return ComparisonStatus.COMPLETE
        if completed == 0:
            return ComparisonStatus.FAILED
        return ComparisonStatus.PARTIAL

    @property
    def all_terminal(self) -> bool:
        return all(e.status not in _UNRESOLVED for e in self.envelopes.values())

    def to_resource(self) -> ComparisonResource:
        return ComparisonResource(
            id=self.id,
            status=self.aggregate_status,
            generated_at=self.generated_at,
            request=self.request,
            snapshot=self.snapshot,
            outcomes=[self.envelopes[m] for m in self.request.models],
            normalization_notes=list(self.normalization_notes),
        )


class StateStore:
    def __init__(self) -> None:
        self._states: dict[str, ComparisonState] = {}

    def put(self, state: ComparisonState) -> None:
        self._states[str(state.id)] = state

    def get(self, comparison_id: str) -> ComparisonState | None:
        return self._states.get(comparison_id)
