"""Persist content-free usage events for model calls outside turn traces."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Literal, cast

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

AI_USAGE_COLLECTION_NAME = "ai_usage"

UsageSource = Literal[
    "lab",
    "judge_jev",
    "summary_generation",
    "title_generation",
    "faq_embedding_query",
    "faq_embedding_index",
    "memory_embedding_query",
    "memory_embedding_index",
]
UsageStatus = Literal["completed", "error"]

USAGE_SOURCE_LABELS: dict[str, str] = {
    "agent_turn": "Turno do agente",
    "lab": "Laboratório",
    "judge_jev": "Judge JEV",
    "summary_generation": "Geração de resumo",
    "title_generation": "Geração de título",
    "faq_embedding_query": "Embedding de consulta FAQ",
    "faq_embedding_index": "Indexação de FAQ",
    "memory_embedding_query": "Embedding de consulta de memória",
    "memory_embedding_index": "Indexação de memória",
}

_USAGE_SOURCES = set(USAGE_SOURCE_LABELS) - {"agent_turn"}
_logger = logging.getLogger(__name__)


class MongoAIUsageRepository:
    """Store model usage metadata without prompts, messages, or vector payloads."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection
        self._indexes_ready = False

    def ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._collection.create_index(
            [("timestamp", DESCENDING), ("_id", DESCENDING)],
            name="ix_ai_usage_timestamp",
        )
        self._collection.create_index(
            [("source", ASCENDING), ("timestamp", DESCENDING)],
            name="ix_ai_usage_source_timestamp",
        )
        self._collection.create_index(
            [("conversation_id", ASCENDING), ("timestamp", DESCENDING)],
            name="ix_ai_usage_conversation_timestamp",
        )
        self._collection.create_index(
            [("trace_id", ASCENDING), ("timestamp", ASCENDING)],
            name="ix_ai_usage_trace_timestamp",
        )
        self._collection.update_one(
            {"_id": "__usage_metadata__"},
            {"$setOnInsert": {"metering_started_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        self._indexes_ready = True

    def get_metering_started_at(self) -> datetime:
        """Return when complete non-trace source metering began in this DB."""
        self.ensure_indexes()
        metadata = self._collection.find_one(
            {"_id": "__usage_metadata__"},
            {"metering_started_at": 1},
        )
        started_at = metadata.get("metering_started_at") if metadata else None
        if not isinstance(started_at, datetime):
            return datetime.now(timezone.utc)
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            return started_at.replace(tzinfo=timezone.utc)
        return started_at.astimezone(timezone.utc)

    def record_usage(  # noqa: PLR0913
        self,
        *,
        event_id: str,
        source: UsageSource,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        status: UsageStatus,
        item_count: int | None = None,
        trace_id: str | None = None,
        conversation_id: str | None = None,
        duration_ms: float | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Upsert one sanitized usage event; telemetry errors never block work."""
        document = _usage_document(
            event_id=event_id,
            source=source,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=status,
            item_count=item_count,
            trace_id=trace_id,
            conversation_id=conversation_id,
            duration_ms=duration_ms,
            timestamp=timestamp,
        )
        try:
            self.ensure_indexes()
            self._collection.replace_one(
                {"_id": document["_id"]}, document, upsert=True
            )
        except Exception:
            _logger.exception("ai_usage_persistence_failed", extra={"source": source})

    def iter_usage(
        self,
        *,
        started_from: datetime,
        started_to: datetime,
    ) -> Iterator[dict[str, Any]]:
        """Stream usage events in an inclusive UTC time range."""
        if started_from.tzinfo is None or started_to.tzinfo is None:
            raise ValueError("O período precisa incluir timezone")
        self.ensure_indexes()
        query = {
            "timestamp": {
                "$gte": started_from.astimezone(timezone.utc),
                "$lte": started_to.astimezone(timezone.utc),
            }
        }
        projection = {
            "source": 1,
            "model": 1,
            "input_tokens": 1,
            "output_tokens": 1,
            "status": 1,
            "timestamp": 1,
            "item_count": 1,
            "trace_id": 1,
            "conversation_id": 1,
            "duration_ms": 1,
        }
        cursor = self._collection.find(query, projection).sort(
            [("timestamp", ASCENDING), ("_id", ASCENDING)]
        )
        return cast(Iterator[dict[str, Any]], cursor)

    def iter_trace_usage(self, trace_id: str) -> Iterator[dict[str, Any]]:
        """Stream content-free usage events correlated to one trace."""
        if not trace_id.strip():
            raise ValueError("trace_id não pode estar vazio")
        self.ensure_indexes()
        projection = {
            "_id": 0,
            "source": 1,
            "model": 1,
            "input_tokens": 1,
            "output_tokens": 1,
            "status": 1,
            "timestamp": 1,
            "duration_ms": 1,
        }
        cursor = self._collection.find({"trace_id": trace_id.strip()}, projection).sort(
            [("timestamp", ASCENDING), ("_id", ASCENDING)]
        )
        return cast(Iterator[dict[str, Any]], cursor)


def _usage_document(  # noqa: PLR0913
    *,
    event_id: str,
    source: UsageSource,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    status: UsageStatus,
    item_count: int | None,
    trace_id: str | None,
    conversation_id: str | None,
    duration_ms: float | None,
    timestamp: datetime | None,
) -> dict[str, Any]:
    _validate_usage_identity(event_id, source, model)
    _validate_usage_counts(input_tokens, output_tokens, item_count)
    _validate_usage_duration(duration_ms)
    event_timestamp = timestamp or datetime.now(timezone.utc)
    if event_timestamp.tzinfo is None or event_timestamp.utcoffset() is None:
        raise ValueError("timestamp precisa incluir timezone")
    document: dict[str, Any] = {
        "_id": event_id.strip(),
        "source": source,
        "model": model.strip(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "status": status,
        "timestamp": event_timestamp.astimezone(timezone.utc),
    }
    if item_count is not None:
        document["item_count"] = item_count
    if duration_ms is not None:
        document["duration_ms"] = float(duration_ms)
    if trace_id:
        document["trace_id"] = trace_id
    if conversation_id:
        document["conversation_id"] = conversation_id
    return document


def _validate_usage_identity(event_id: str, source: UsageSource, model: str) -> None:
    if source not in _USAGE_SOURCES:
        raise ValueError("Origem de uso inválida")
    if not event_id.strip() or not model.strip():
        raise ValueError("event_id e model são obrigatórios")


def _validate_usage_counts(
    input_tokens: int | None,
    output_tokens: int | None,
    item_count: int | None,
) -> None:
    for name, value in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("item_count", item_count),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(f"{name} precisa ser um inteiro não negativo")


def _validate_usage_duration(duration_ms: float | None) -> None:
    if duration_ms is not None and (
        isinstance(duration_ms, bool)
        or not isinstance(duration_ms, (int, float))
        or not isfinite(duration_ms)
        or duration_ms < 0
    ):
        raise ValueError("duration_ms precisa ser finito e não negativo")


@contextmanager
def bind_usage_conversation(conversation_id: str) -> Iterator[None]:
    """Attach a conversation ID to background usage calls for the current task."""
    token: Token[str | None] = _USAGE_CONVERSATION.set(conversation_id)
    try:
        yield
    finally:
        _USAGE_CONVERSATION.reset(token)


_USAGE_CONVERSATION: ContextVar[str | None] = ContextVar(
    "ai_usage_conversation_id", default=None
)


def current_usage_conversation_id() -> str | None:
    return _USAGE_CONVERSATION.get()


def record_usage_safely(  # noqa: PLR0913
    repository: MongoAIUsageRepository | None,
    *,
    event_id: str,
    source: UsageSource,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    status: UsageStatus,
    item_count: int | None = None,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Read active trace context and persist usage without affecting the caller."""
    if repository is None:
        return
    try:
        from src.observability.logger.log_context import get_log_context

        log_context = get_log_context()
        repository.record_usage(
            event_id=event_id,
            source=source,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=status,
            item_count=item_count,
            trace_id=trace_id or (log_context.trace_id if log_context else None),
            conversation_id=(
                conversation_id
                or current_usage_conversation_id()
                or (log_context.conversation_id if log_context else None)
            ),
            duration_ms=duration_ms,
        )
    except Exception:
        _logger.exception("ai_usage_recording_failed", extra={"source": source})
