from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from src.observability.trace_repository import (
    MAX_TRACE_PAGE_SIZE,
    MongoTraceRepository,
)

START = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
END = START + timedelta(seconds=1)


class FakeCursor(list[dict[str, Any]]):
    def sort(self, order: list[tuple[str, int]]) -> FakeCursor:
        self.sort_order = order
        return self

    def skip(self, count: int) -> FakeCursor:
        del self[:count]
        return self

    def limit(self, count: int) -> FakeCursor:
        del self[count:]
        return self


class FakeCollection:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.indexes: list[tuple[Any, str]] = []
        self.last_query: dict[str, Any] | None = None
        self.last_projection: dict[str, int] | None = None
        self.last_sort: Any = None

    def create_index(self, keys: Any, *, name: str) -> None:
        self.indexes.append((keys, name))

    def replace_one(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
        *,
        upsert: bool,
    ) -> None:
        assert upsert is True
        self.documents[query["_id"]] = document

    def find_one(
        self,
        query: dict[str, Any],
        projection: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        self.last_query = query
        self.last_projection = projection
        return self.documents.get(query.get("_id", ""))

    def find(
        self,
        query: dict[str, Any],
        projection: dict[str, int] | None = None,
    ) -> FakeCursor:
        self.last_query = query
        self.last_projection = projection
        return FakeCursor(list(self.documents.values()))

    def count_documents(self, query: dict[str, Any]) -> int:
        self.last_query = query
        return len(self.documents)


def _span(
    span_id: str,
    kind: str,
    *,
    status: str = "completed",
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "span_id": span_id,
        "parent_span_id": "trace-1",
        "name": f"agent.{kind}",
        "kind": kind,
        "started_at": START,
        "status": status,
        "ended_at": END,
        "duration_ms": 12,
        "model": "gpt-6-luna" if kind == "llm" else None,
        "input_tokens": 10 if kind == "llm" else None,
        "output_tokens": 5 if kind == "llm" else None,
        "error_type": None,
        "attributes": attributes or {},
        "unapproved_payload": "never persist",
    }


def _trace() -> dict[str, Any]:
    return {
        "trace_id": " trace-1 ",
        "conversation_id": " conversation-1 ",
        "environment": " qa ",
        "started_at": START,
        "status": "completed",
        "ended_at": END,
        "duration_ms": 1_000,
        "fallback_used": False,
        "spans": [
            _span(
                "tool-1",
                "tool",
                status="error",
                attributes={
                    "langgraph_node": "faq",
                    "tool_status": "partial",
                    "tool_error_code": "TOOL_TIMEOUT",
                    "tool_results_count": 2,
                    "tool_evidence_count": 1,
                    "secret": "do not keep",
                    "tool_status_extra": "ignored",
                    "tool_results_count_bad": -1,
                },
            ),
            _span("llm-1", "llm"),
        ],
        "logs": [
            {
                "log_id": "log-1",
                "trace_id": "trace-1",
                "conversation_id": "conversation-1",
                "timestamp": END,
                "level": "info",
                "logger": "agent.faq",
                "message": "tool completed",
                "span_id": "tool-1",
                "agent_id": "faq",
                "event": "tool_call",
                "error_type": None,
                "attributes": {
                    "event": "tool_call",
                    "results_count": 2,
                    "private_prompt": "not stored",
                    "bad": [],
                },
            }
        ],
        "secret": "not stored",
    }


def test_save_get_list_count_and_iter_traces_use_sanitized_documents() -> None:
    collection = FakeCollection()
    repository = MongoTraceRepository(collection)  # type: ignore[arg-type]
    repository.save_trace(_trace())

    assert len(collection.indexes) == 3
    stored = collection.documents["trace-1"]
    assert stored["_id"] == "trace-1"
    assert stored["conversation_id"] == "conversation-1"
    assert "secret" not in stored
    assert stored["spans"][0]["attributes"] == {
        "langgraph_node": "faq",
        "tool_status": "partial",
        "tool_error_code": "TOOL_TIMEOUT",
        "tool_results_count": 2,
        "tool_evidence_count": 1,
    }
    assert stored["spans"][1]["attributes"] == {}
    assert stored["logs"][0]["attributes"] == {
        "event": "tool_call",
        "results_count": 2,
    }
    assert stored["logs"][0]["level"] == "INFO"

    assert repository.get_trace("trace-1") == stored
    with pytest.raises(ValueError, match="trace_id"):
        repository.get_trace(" ")

    listed = repository.list_traces(
        started_from=START,
        started_to=END,
        conversation_id="conversation-1",
        conversation_ids=["conversation-1", "conversation-2"],
        environment="qa",
        status="completed",
        limit=1,
        offset=0,
        include_spans=False,
    )
    assert listed == [stored]
    assert collection.last_query == {
        "conversation_id": {
            "$in": ["conversation-1", "conversation-2"],
            "$eq": "conversation-1",
        },
        "environment": "qa",
        "status": "completed",
        "started_at": {"$gte": START, "$lte": END},
    }
    assert collection.last_projection == {"spans": 0, "logs": 0}
    assert repository.count_traces(conversation_id="conversation-1") == 1
    assert list(repository.iter_traces(started_from=START, started_to=END)) == [stored]
    assert len(collection.indexes) == 3


def test_repository_query_bounds_and_filter_validation() -> None:
    repository = MongoTraceRepository(FakeCollection())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="limit"):
        repository.list_traces(limit=MAX_TRACE_PAGE_SIZE + 1)
    with pytest.raises(ValueError, match="offset"):
        repository.list_traces(offset=-1)
    with pytest.raises(ValueError, match="conversation_id"):
        repository.count_traces(conversation_id=" ")
    with pytest.raises(ValueError, match="environment"):
        repository.iter_traces(started_from=START, started_to=END, environment=" ")
    with pytest.raises(ValueError, match="started_from"):
        repository.count_traces(started_from=END, started_to=START)

    assert (
        MongoTraceRepository._build_query(
            started_from=None,
            started_to=None,
            conversation_id=None,
            conversation_ids=None,
            environment=None,
            status=None,
        )
        == {}
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("trace_id", "", "trace_id"),
        ("conversation_id", "", "conversation_id"),
        ("environment", "", "environment"),
        ("status", "running", "finalizado"),
        ("started_at", "bad", "datetime"),
        ("ended_at", datetime(2026, 1, 1), "timezone"),
        ("duration_ms", True, "duration_ms"),
        ("duration_ms", -1, "duration_ms"),
        ("spans", None, "spans"),
        ("logs", None, "logs"),
    ],
)
def test_invalid_trace_fields_are_rejected(
    field: str,
    value: Any,
    message: str,
) -> None:
    trace = _trace()
    trace[field] = value
    with pytest.raises(ValueError, match=message):
        MongoTraceRepository._sanitize_trace(trace)


def test_trace_rejects_excess_logs_and_logs_for_unknown_spans() -> None:
    trace = _trace()
    trace["logs"] = [{}] * 1_001
    with pytest.raises(ValueError, match="no máximo"):
        MongoTraceRepository._sanitize_trace(trace)

    trace = _trace()
    trace["logs"][0]["span_id"] = "missing"
    with pytest.raises(ValueError, match="referenciar"):
        MongoTraceRepository._sanitize_trace(trace)


@pytest.mark.parametrize(
    "span",
    [
        None,
        {},
        {"span_id": "x", "name": "", "kind": "tool", "status": "running"},
        {"span_id": "x", "name": "n", "kind": "", "status": "running"},
        {"span_id": "x", "name": "n", "kind": "tool", "status": "unknown"},
    ],
)
def test_invalid_span_shapes_are_rejected(span: Any) -> None:
    with pytest.raises(ValueError):
        MongoTraceRepository._sanitize_span(span)


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
@pytest.mark.parametrize("value", [True, -1, 1.5])
def test_span_token_counts_must_be_non_negative_integers(
    field: str,
    value: Any,
) -> None:
    span = _span("llm-1", "llm")
    span[field] = value
    with pytest.raises(ValueError, match=field):
        MongoTraceRepository._sanitize_span(span)


def test_span_duration_timestamps_and_untrusted_attributes_are_filtered() -> None:
    span = _span(
        "tool-1",
        "tool",
        attributes={
            "tool_status": "unknown",
            "tool_error_code": "unsafe-code",
            "tool_results_count": True,
            "tool_evidence_count": -1,
            "agent_id": "faq",
            "prompt_version": 3,
            "raw_tool_result": "private",
        },
    )
    span["duration_ms"] = None
    span["ended_at"] = None
    sanitized = MongoTraceRepository._sanitize_span(span)
    assert sanitized["duration_ms"] is None
    assert sanitized["ended_at"] is None
    assert sanitized["attributes"] == {"agent_id": "faq", "prompt_version": 3}

    span["attributes"] = []
    assert MongoTraceRepository._sanitize_span(span)["attributes"] == {}
    span["duration_ms"] = "12"
    with pytest.raises(ValueError, match="duration_ms"):
        MongoTraceRepository._sanitize_span(span)


def test_invalid_log_fields_and_attribute_values_are_rejected() -> None:
    valid_log = _trace()["logs"][0]
    invalid_variants = [
        ({**valid_log, "log_id": ""}, "log_id"),
        ({**valid_log, "level": "DEBUG"}, "level"),
        ({**valid_log, "logger": ""}, "logger"),
        ({**valid_log, "message": ""}, "message"),
        ({**valid_log, "trace_id": "other"}, "trace_id"),
        ({**valid_log, "conversation_id": "other"}, "conversation_id"),
        ({**valid_log, "span_id": ""}, "span_id"),
        ({**valid_log, "timestamp": None}, "datetime"),
        ({**valid_log, "attributes": {"agent_id": []}}, "agent_id"),
    ]
    for log, message in invalid_variants:
        with pytest.raises(ValueError, match=message):
            MongoTraceRepository._sanitize_log(
                log,
                trace_id="trace-1",
                conversation_id="conversation-1",
            )

    with pytest.raises(ValueError, match="objeto"):
        MongoTraceRepository._sanitize_log(
            [],
            trace_id="trace-1",
            conversation_id="conversation-1",
        )
