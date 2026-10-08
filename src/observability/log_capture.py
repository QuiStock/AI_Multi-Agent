"""Capture safe Python log records produced inside one conversation trace."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import Any
from uuid import uuid4

from src.observability.log_context import bind_trace_context, get_log_context

MAX_CAPTURED_LOGS = 1_000
MAX_LOG_MESSAGE_LENGTH = 4_000

_EMAIL_PATTERN = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+\S+")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*\S+"
)
_SAFE_ATTRIBUTE_KEYS = {
    "event",
    "reason_code",
    "route",
    "outcome",
    "target_agent",
    "evidence_count",
    "citation_count",
    "message_count",
    "duration_ms",
    "candidates_count",
    "results_count",
    "no_results",
    "files_discovered",
    "documents_found",
    "chunk_count",
    "embedding_count",
    "collection_name",
    "model_name",
    "error_type",
    "status",
}
_LEVEL_LOCK = RLock()
_ACTIVE_CAPTURES = 0
_ORIGINAL_SRC_LEVEL: int | None = None


def _safe_text(value: object, *, maximum: int) -> str:
    text = str(value)
    text = _EMAIL_PATTERN.sub("[email redigido]", text)
    text = _BEARER_PATTERN.sub("Bearer [segredo redigido]", text)
    text = _SECRET_PATTERN.sub(r"\1=[segredo redigido]", text)
    return text[:maximum]


def _safe_attributes(record: logging.LogRecord) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for key in _SAFE_ATTRIBUTE_KEYS:
        value = getattr(record, key, None)
        if isinstance(value, str):
            attributes[key] = _safe_text(value, maximum=256)
        elif isinstance(value, (bool, int, float)):
            attributes[key] = value
    return attributes


class CorrelatedLogCapture(logging.Handler):
    """Buffer records that run while this trace is the active log context."""

    def __init__(
        self,
        *,
        trace_id: str,
        conversation_id: str,
        event_publisher: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(level=logging.INFO)
        self.trace_id = trace_id
        self.conversation_id = conversation_id
        self._event_publisher = event_publisher
        self.records: list[dict[str, Any]] = []
        self.dropped_count = 0
        self._records_lock = Lock()
        self._source_logger = logging.getLogger("src")

    @contextmanager
    def capture(self) -> Iterator[CorrelatedLogCapture]:
        global _ACTIVE_CAPTURES, _ORIGINAL_SRC_LEVEL

        with _LEVEL_LOCK:
            if _ACTIVE_CAPTURES == 0:
                _ORIGINAL_SRC_LEVEL = self._source_logger.level
                if self._source_logger.getEffectiveLevel() > logging.INFO:
                    self._source_logger.setLevel(logging.INFO)
            _ACTIVE_CAPTURES += 1

        self._source_logger.addHandler(self)
        try:
            with bind_trace_context(
                trace_id=self.trace_id,
                conversation_id=self.conversation_id,
            ):
                yield self
        finally:
            self._source_logger.removeHandler(self)
            with _LEVEL_LOCK:
                _ACTIVE_CAPTURES -= 1
                if _ACTIVE_CAPTURES == 0 and _ORIGINAL_SRC_LEVEL is not None:
                    self._source_logger.setLevel(_ORIGINAL_SRC_LEVEL)
                    _ORIGINAL_SRC_LEVEL = None

    def emit(self, record: logging.LogRecord) -> None:
        context = get_log_context()
        if context is None or context.trace_id != self.trace_id:
            return

        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        error_type = None
        if record.exc_info and record.exc_info[0] is not None:
            error_type = record.exc_info[0].__name__

        event = getattr(record, "event", None)
        entry = {
            "log_id": str(uuid4()),
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc),
            "level": record.levelname,
            "logger": _safe_text(record.name, maximum=256),
            "message": _safe_text(message, maximum=MAX_LOG_MESSAGE_LENGTH),
            "trace_id": context.trace_id,
            "span_id": context.span_id,
            "conversation_id": context.conversation_id,
            "agent_id": context.agent_id,
            "event": _safe_text(event, maximum=256) if isinstance(event, str) else None,
            "error_type": error_type,
            "attributes": _safe_attributes(record),
        }

        with self._records_lock:
            if len(self.records) >= MAX_CAPTURED_LOGS:
                self.dropped_count += 1
                return
            self.records.append(entry)

        if self._event_publisher is not None:
            try:
                self._event_publisher(entry)
            except Exception:
                # A failed live feed must not affect the graph or log capture.
                return
