"""Bounded in-process event feed for traces currently executing."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Literal

MAX_LIVE_TRACE_EVENTS = 4_000
MAX_ACTIVE_TRACES = 200
MAX_LIVE_TRACE_FEED_PAGE_SIZE = 1_000

LiveEventType = Literal["trace", "span", "log"]


class LiveTraceStore:
    """Publish recent trace/span/log events for short-interval UI polling.

    The feed is intentionally process-local and bounded. Durable trace data is
    still written to MongoDB after the conversation turn finishes.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_LIVE_TRACE_EVENTS)
        self._active_traces: dict[str, dict[str, Any]] = {}
        self._sequence = 0

    def start_trace(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        environment: str,
    ) -> None:
        started_at = datetime.now(timezone.utc)
        with self._lock:
            self._active_traces[trace_id] = {
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "environment": environment,
                "started_at": started_at,
            }
            while len(self._active_traces) > MAX_ACTIVE_TRACES:
                oldest_trace_id = next(iter(self._active_traces))
                self._active_traces.pop(oldest_trace_id, None)
            self._append_event_locked(
                event_type="trace",
                phase="started",
                trace_id=trace_id,
                conversation_id=conversation_id,
                timestamp=started_at,
                data={"environment": environment},
            )

    def publish(self, event: Mapping[str, Any]) -> None:
        event_type = event.get("event_type")
        phase = event.get("phase")
        trace_id = event.get("trace_id")
        conversation_id = event.get("conversation_id")
        timestamp = event.get("timestamp")
        data = event.get("data")
        if event_type not in {"trace", "span", "log"}:
            return
        if not isinstance(phase, str) or not isinstance(trace_id, str):
            return
        if not isinstance(conversation_id, str) or not isinstance(data, Mapping):
            return
        if not isinstance(timestamp, datetime):
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        with self._lock:
            self._append_event_locked(
                event_type=event_type,
                phase=phase,
                trace_id=trace_id,
                conversation_id=conversation_id,
                timestamp=timestamp,
                data=dict(data),
            )

    def publish_log(self, log: Mapping[str, Any]) -> None:
        timestamp = log.get("timestamp")
        self.publish(
            {
                "event_type": "log",
                "phase": "recorded",
                "trace_id": log.get("trace_id"),
                "conversation_id": log.get("conversation_id"),
                "timestamp": timestamp,
                "data": {
                    key: value
                    for key, value in log.items()
                    if key not in {"trace_id", "conversation_id", "timestamp"}
                },
            }
        )

    def finish_trace(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        status: Literal["completed", "error"],
        duration_ms: float | None,
    ) -> None:
        timestamp = datetime.now(timezone.utc)
        with self._lock:
            self._active_traces.pop(trace_id, None)
            self._append_event_locked(
                event_type="trace",
                phase=status,
                trace_id=trace_id,
                conversation_id=conversation_id,
                timestamp=timestamp,
                data={"duration_ms": duration_ms},
            )

    def get_feed(self, *, after: int = 0, limit: int = 500) -> dict[str, Any]:
        if after < 0:
            raise ValueError("after precisa ser não negativo")
        if not 1 <= limit <= MAX_LIVE_TRACE_FEED_PAGE_SIZE:
            raise ValueError(
                f"limit precisa estar entre 1 e {MAX_LIVE_TRACE_FEED_PAGE_SIZE}"
            )

        with self._lock:
            events = list(self._events)
            latest_sequence = self._sequence
            active_traces = [dict(trace) for trace in self._active_traces.values()]

        oldest_sequence = events[0]["sequence"] if events else latest_sequence + 1
        reset_required = after > 0 and after < oldest_sequence - 1
        cursor = max(after, oldest_sequence - 1) if reset_required else after
        available = [event for event in events if event["sequence"] > cursor]
        page = available[:limit]
        next_cursor = page[-1]["sequence"] if page else cursor
        return {
            "events": page,
            "active_traces": active_traces,
            "next_cursor": next_cursor,
            "has_more": next_cursor < latest_sequence,
            "reset_required": reset_required,
        }

    def _append_event_locked(  # noqa: PLR0913
        self,
        *,
        event_type: LiveEventType,
        phase: str,
        trace_id: str,
        conversation_id: str,
        timestamp: datetime,
        data: dict[str, Any],
    ) -> None:
        self._sequence += 1
        self._events.append(
            {
                "sequence": self._sequence,
                "event_type": event_type,
                "phase": phase,
                "trace_id": trace_id,
                "conversation_id": conversation_id,
                "timestamp": timestamp,
                "data": data,
            }
        )


live_trace_store = LiveTraceStore()
