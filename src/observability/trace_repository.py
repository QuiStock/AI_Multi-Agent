"""MongoDB persistence for agent execution traces."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Literal, cast

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

TRACE_COLLECTION_NAME = "agent_traces"
MAX_TRACE_PAGE_SIZE = 200
MAX_TRACE_LOG_COUNT = 1_000

TraceStatus = Literal["completed", "error"]

_TRACE_FIELDS = {
    "trace_id",
    "conversation_id",
    "environment",
    "started_at",
    "status",
    "ended_at",
    "duration_ms",
    "spans",
    "logs",
}
_SPAN_FIELDS = {
    "span_id",
    "parent_span_id",
    "name",
    "kind",
    "started_at",
    "status",
    "ended_at",
    "duration_ms",
    "model",
    "input_tokens",
    "output_tokens",
    "error_type",
    "attributes",
}
_SAFE_SPAN_ATTRIBUTES = {
    "langgraph_node",
    "agent_id",
    "prompt_version",
    "tool_status",
    "tool_error_code",
    "tool_results_count",
    "tool_evidence_count",
}
_TOOL_SUMMARY_STATUSES = {"success", "partial", "error"}
_TOOL_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SAFE_LOG_ATTRIBUTES = {
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
_VALID_LOG_LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} precisa ser datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} precisa incluir timezone")
    return value.astimezone(timezone.utc)


def _bounded_duration(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{field_name} precisa ser um número não negativo")
    return float(value)


class MongoTraceRepository:
    """Store one completed trace document per graph invocation."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection
        self._indexes_ready = False

    def ensure_indexes(self) -> None:
        """Create indexes for trace lookup, conversation history, and date filters."""
        if self._indexes_ready:
            return

        self._collection.create_index(
            [("started_at", DESCENDING), ("_id", DESCENDING)],
            name="ix_agent_traces_started_at",
        )
        self._collection.create_index(
            [
                ("conversation_id", ASCENDING),
                ("started_at", DESCENDING),
                ("_id", DESCENDING),
            ],
            name="ix_agent_traces_conversation_started",
        )
        self._collection.create_index(
            [
                ("environment", ASCENDING),
                ("started_at", DESCENDING),
                ("_id", DESCENDING),
            ],
            name="ix_agent_traces_environment_started",
        )
        self._indexes_ready = True

    def save_trace(self, trace: Mapping[str, Any]) -> None:
        """Upsert a sanitized final trace, keyed by its trace ID."""
        self.ensure_indexes()
        document = self._sanitize_trace(trace)
        trace_id = document["trace_id"]
        document["_id"] = trace_id
        self._collection.replace_one({"_id": trace_id}, document, upsert=True)

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Return one trace by ID, or None when it does not exist."""
        if not trace_id.strip():
            raise ValueError("trace_id é obrigatório")
        self.ensure_indexes()
        return cast(
            dict[str, Any] | None,
            self._collection.find_one({"_id": trace_id.strip()}),
        )

    def list_traces(  # noqa: PLR0913
        self,
        *,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        conversation_id: str | None = None,
        conversation_ids: Sequence[str] | None = None,
        environment: str | None = None,
        status: TraceStatus | None = None,
        limit: int = 100,
        offset: int = 0,
        include_spans: bool = True,
    ) -> list[dict[str, Any]]:
        """List traces in reverse chronological order with bounded filters."""
        if not 1 <= limit <= MAX_TRACE_PAGE_SIZE:
            raise ValueError(f"limit precisa estar entre 1 e {MAX_TRACE_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset não pode ser negativo")

        query = self._build_query(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            conversation_ids=conversation_ids,
            environment=environment,
            status=status,
        )

        self.ensure_indexes()
        projection = None if include_spans else {"spans": 0, "logs": 0}
        cursor = (
            self._collection.find(query, projection)
            .sort([("started_at", DESCENDING), ("_id", DESCENDING)])
            .skip(offset)
            .limit(limit)
        )
        return list(cursor)

    def count_traces(  # noqa: PLR0913
        self,
        *,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
        conversation_id: str | None = None,
        conversation_ids: Sequence[str] | None = None,
        environment: str | None = None,
        status: TraceStatus | None = None,
    ) -> int:
        """Count all traces matching the supplied filters."""
        self.ensure_indexes()
        query = self._build_query(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            conversation_ids=conversation_ids,
            environment=environment,
            status=status,
        )
        return int(self._collection.count_documents(query))

    def iter_traces(  # noqa: PLR0913
        self,
        *,
        started_from: datetime,
        started_to: datetime,
        conversation_id: str | None = None,
        conversation_ids: Sequence[str] | None = None,
        environment: str | None = None,
        status: TraceStatus | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream matching trace data for complete metric aggregation."""
        self.ensure_indexes()
        query = self._build_query(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            conversation_ids=conversation_ids,
            environment=environment,
            status=status,
        )
        projection = {
            "_id": 0,
            "status": 1,
            "duration_ms": 1,
            "fallback_used": 1,
            "spans": 1,
        }
        cursor = self._collection.find(query, projection).sort(
            [("started_at", ASCENDING), ("_id", ASCENDING)]
        )
        yield from cursor

    @staticmethod
    def _build_query(  # noqa: C901, PLR0913
        *,
        started_from: datetime | None,
        started_to: datetime | None,
        conversation_id: str | None,
        conversation_ids: Sequence[str] | None,
        environment: str | None,
        status: TraceStatus | None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if conversation_id is not None:
            if not conversation_id.strip():
                raise ValueError("conversation_id não pode estar vazio")
            query["conversation_id"] = conversation_id.strip()
        if conversation_ids is not None:
            id_filter: dict[str, Any] = {"$in": list(conversation_ids)}
            if conversation_id is not None:
                id_filter["$eq"] = conversation_id.strip()
            query["conversation_id"] = id_filter
        if environment is not None:
            if not environment.strip():
                raise ValueError("environment não pode estar vazio")
            query["environment"] = environment.strip()
        if status is not None:
            query["status"] = status

        time_filter: dict[str, datetime] = {}
        if started_from is not None:
            time_filter["$gte"] = _aware_utc(started_from, "started_from")
        if started_to is not None:
            time_filter["$lte"] = _aware_utc(started_to, "started_to")
        if time_filter:
            query["started_at"] = time_filter
        if (
            started_from is not None
            and started_to is not None
            and _aware_utc(started_from, "started_from")
            > _aware_utc(started_to, "started_to")
        ):
            raise ValueError("started_from não pode ser posterior a started_to")
        return query

    @classmethod
    def _sanitize_trace(cls, trace: Mapping[str, Any]) -> dict[str, Any]:
        trace_id = trace.get("trace_id")
        conversation_id = trace.get("conversation_id")
        environment = trace.get("environment")
        status = trace.get("status")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError("trace_id é obrigatório")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError("conversation_id é obrigatório")
        if not isinstance(environment, str) or not environment.strip():
            raise ValueError("environment é obrigatório")
        if status not in {"completed", "error"}:
            raise ValueError("O trace precisa estar finalizado antes de ser salvo")

        started_at = _aware_utc(trace.get("started_at"), "started_at")
        ended_at = _aware_utc(trace.get("ended_at"), "ended_at")
        spans = trace.get("spans")
        if not isinstance(spans, list):
            raise ValueError("spans precisa ser uma lista")
        logs = trace.get("logs", [])
        if not isinstance(logs, list):
            raise ValueError("logs precisa ser uma lista")
        if len(logs) > MAX_TRACE_LOG_COUNT:
            raise ValueError(
                f"Um trace pode conter no máximo {MAX_TRACE_LOG_COUNT} logs"
            )

        document = {
            key: trace[key]
            for key in _TRACE_FIELDS
            if key in trace and key not in {"started_at", "ended_at", "spans"}
        }
        document["trace_id"] = trace_id.strip()
        document["conversation_id"] = conversation_id.strip()
        document["environment"] = environment.strip()
        document["started_at"] = started_at
        document["ended_at"] = ended_at
        document["duration_ms"] = _bounded_duration(
            trace.get("duration_ms"), "duration_ms"
        )
        document["spans"] = [cls._sanitize_span(span) for span in spans]
        span_ids = {span["span_id"] for span in document["spans"]}
        sanitized_logs = [
            cls._sanitize_log(
                log,
                trace_id=document["trace_id"],
                conversation_id=document["conversation_id"],
            )
            for log in logs
        ]
        if any(log["span_id"] not in span_ids for log in sanitized_logs):
            raise ValueError("Todo log precisa referenciar um span do trace")
        document["logs"] = sorted(
            sanitized_logs,
            key=lambda log: (log["timestamp"], log["log_id"]),
        )
        return document

    @staticmethod
    def _sanitize_log(  # noqa: C901
        log: object,
        *,
        trace_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        if not isinstance(log, Mapping):
            raise ValueError("Cada log precisa ser um objeto")

        log_id = log.get("log_id")
        level = log.get("level")
        logger = log.get("logger")
        message = log.get("message")
        span_id = log.get("span_id")
        if not isinstance(log_id, str) or not log_id.strip():
            raise ValueError("log_id é obrigatório")
        if not isinstance(level, str) or level.upper() not in _VALID_LOG_LEVELS:
            raise ValueError("level inválido no log")
        if not isinstance(logger, str) or not logger.strip():
            raise ValueError("logger é obrigatório no log")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message é obrigatório no log")
        if log.get("trace_id") != trace_id:
            raise ValueError("trace_id do log não corresponde ao trace")
        if log.get("conversation_id") != conversation_id:
            raise ValueError("conversation_id do log não corresponde ao trace")
        if not isinstance(span_id, str) or not span_id.strip():
            raise ValueError("span_id é obrigatório no log")

        document: dict[str, Any] = {
            "log_id": log_id.strip(),
            "timestamp": _aware_utc(log.get("timestamp"), "log.timestamp"),
            "level": level.upper(),
            "logger": logger.strip()[:256],
            "message": message[:4_000],
            "span_id": span_id.strip(),
        }
        for key in ("agent_id", "event", "error_type"):
            value = log.get(key)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{key} precisa ser string no log")
                document[key] = value[:256]

        attributes = log.get("attributes")
        document["attributes"] = (
            {
                key: value[:256] if isinstance(value, str) else value
                for key, value in attributes.items()
                if key in _SAFE_LOG_ATTRIBUTES
                and isinstance(value, (str, bool, int, float))
            }
            if isinstance(attributes, Mapping)
            else {}
        )
        return document

    @staticmethod
    def _sanitize_span(span: object) -> dict[str, Any]:  # noqa: C901, PLR0912
        if not isinstance(span, Mapping):
            raise ValueError("Cada span precisa ser um objeto")

        span_id = span.get("span_id")
        name = span.get("name")
        kind = span.get("kind")
        status = span.get("status")
        if not isinstance(span_id, str) or not span_id.strip():
            raise ValueError("span_id é obrigatório")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name é obrigatório em cada span")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("kind é obrigatório em cada span")
        if status not in {"running", "completed", "error", "interrupted"}:
            raise ValueError("status inválido em span")

        document = {key: span[key] for key in _SPAN_FIELDS if key in span}
        document["span_id"] = span_id.strip()
        document["name"] = name.strip()
        document["started_at"] = _aware_utc(span.get("started_at"), "span.started_at")
        ended_at = span.get("ended_at")
        document["ended_at"] = (
            _aware_utc(ended_at, "span.ended_at") if ended_at is not None else None
        )
        document["duration_ms"] = _bounded_duration(
            span.get("duration_ms"), "span.duration_ms"
        )

        attributes = span.get("attributes")
        if isinstance(attributes, Mapping):
            safe_attributes: dict[str, str | int | float | bool] = {}
            for key, value in attributes.items():
                if key not in _SAFE_SPAN_ATTRIBUTES:
                    continue
                if key == "tool_status":
                    if isinstance(value, str) and value in _TOOL_SUMMARY_STATUSES:
                        safe_attributes[key] = value
                    continue
                if key == "tool_error_code":
                    if (
                        isinstance(value, str)
                        and _TOOL_ERROR_CODE_PATTERN.fullmatch(value) is not None
                    ):
                        safe_attributes[key] = value
                    continue
                if key in {"tool_results_count", "tool_evidence_count"}:
                    if (
                        isinstance(value, int)
                        and not isinstance(value, bool)
                        and value >= 0
                    ):
                        safe_attributes[key] = value
                    continue
                if isinstance(value, (str, int, float, bool)):
                    safe_attributes[key] = value
            document["attributes"] = safe_attributes
        else:
            document["attributes"] = {}

        for token_field in ("input_tokens", "output_tokens"):
            token_count = document.get(token_field)
            if token_count is not None and (
                isinstance(token_count, bool)
                or not isinstance(token_count, int)
                or token_count < 0
            ):
                raise ValueError(f"{token_field} precisa ser inteiro não negativo")

        return document
