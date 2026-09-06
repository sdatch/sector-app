"""
In-process event bus. One Channel per comparison holds an append-only event log
(so `Last-Event-ID` reconnects never force recomputation) and a set of live
subscriber queues. This maps 1:1 onto the SSE frame vocabulary of endpoint spec
§5, and onto Redis Streams when replicas arrive (the log *is* the stream).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    id: int
    type: str  # outcome | progress | comparison | heartbeat
    data: dict

    def to_sse(self) -> str:
        # heartbeat carries no id (transient); all others are resumable.
        prefix = "" if self.type == "heartbeat" else f"id: {self.id}\n"
        return (
            f"{prefix}event: {self.type}\n"
            f"data: {json.dumps(self.data, separators=(',', ':'))}\n\n"
        )


class Channel:
    """Per-comparison event log + live subscribers. All mutation happens in the
    event loop thread with no `await` in the critical sections, so appends and
    subscribes are atomic relative to each other (no lost/duplicate events)."""

    def __init__(self) -> None:
        self._log: list[Event] = []
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self.closed = False

    def publish(self, type_: str, data: dict) -> Event:
        event = Event(id=len(self._log) + 1, type=type_, data=data)
        self._log.append(event)
        for q in self._subscribers:
            q.put_nowait(event)
        return event

    def subscribe(
        self, last_event_id: int = 0
    ) -> tuple[asyncio.Queue[Event], list[Event]]:
        """Register a live subscriber and atomically capture the backlog after
        `last_event_id`. Backlog events are those already logged; the queue
        receives only events published after this call — no gap, no overlap."""
        backlog = [e for e in self._log if e.id > last_event_id]
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(q)
        return q, backlog

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(q)

    def close(self) -> None:
        self.closed = True


class ChannelRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def create(self, comparison_id: str) -> Channel:
        channel = Channel()
        self._channels[comparison_id] = channel
        return channel

    def get(self, comparison_id: str) -> Channel | None:
        return self._channels.get(comparison_id)

    def drop(self, comparison_id: str) -> None:
        self._channels.pop(comparison_id, None)
