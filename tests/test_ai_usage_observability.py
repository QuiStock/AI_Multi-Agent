from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.observability.ai_usage import AIUsageCallbackHandler, invoke_with_usage
from src.observability.ai_usage_repository import (
    MongoAIUsageRepository,
    bind_usage_conversation,
    current_usage_conversation_id,
    record_usage_safely,
)

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


class FakeCursor(list[dict[str, Any]]):
    def sort(self, order: list[tuple[str, int]]) -> FakeCursor:
        self.sort_order = order
        return self


class FakeCollection:
    def __init__(self) -> None:
        self.indexes: list[tuple[Any, str]] = []
        self.documents: dict[str, dict[str, Any]] = {}
        self.fail_writes = False
        self.query: dict[str, Any] | None = None
        self.projection: dict[str, int] | None = None

    def create_index(self, keys: Any, *, name: str) -> None:
        self.indexes.append((keys, name))

    def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        *,
        upsert: bool,
    ) -> None:
        if upsert and query["_id"] not in self.documents:
            self.documents[query["_id"]] = {
                "_id": query["_id"],
                **update["$setOnInsert"],
            }

    def find_one(
        self,
        query: dict[str, Any],
        projection: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        return self.documents.get(query["_id"])

    def replace_one(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
        *,
        upsert: bool,
    ) -> None:
        if self.fail_writes:
            raise RuntimeError("database unavailable")
        self.documents[query["_id"]] = document

    def find(
        self,
        query: dict[str, Any],
        projection: dict[str, int],
    ) -> FakeCursor:
        self.query = query
        self.projection = projection
        return FakeCursor(
            [
                item
                for key, item in self.documents.items()
                if key != "__usage_metadata__"
            ]
        )


def _repository() -> tuple[MongoAIUsageRepository, FakeCollection]:
    collection = FakeCollection()
    return MongoAIUsageRepository(collection), collection


def test_usage_repository_indexes_upserts_and_reads_metering_start() -> None:
    repository, collection = _repository()
    repository.ensure_indexes()
    repository.ensure_indexes()
    assert len(collection.indexes) == 3

    stored_start = collection.documents["__usage_metadata__"]["metering_started_at"]
    assert repository.get_metering_started_at() == stored_start

    repository.record_usage(
        event_id=" event-1 ",
        source="lab",
        model=" gpt-6-luna ",
        input_tokens=8,
        output_tokens=3,
        item_count=1,
        status="completed",
        trace_id="trace-1",
        conversation_id="conversation-1",
        timestamp=NOW,
    )
    event = collection.documents["event-1"]
    assert event == {
        "_id": "event-1",
        "source": "lab",
        "model": "gpt-6-luna",
        "input_tokens": 8,
        "output_tokens": 3,
        "item_count": 1,
        "status": "completed",
        "trace_id": "trace-1",
        "conversation_id": "conversation-1",
        "timestamp": NOW,
    }

    results = list(
        repository.iter_usage(
            started_from=NOW - timedelta(seconds=1),
            started_to=NOW,
        )
    )
    assert results == [event]
    assert collection.query == {
        "timestamp": {"$gte": NOW - timedelta(seconds=1), "$lte": NOW}
    }
    assert collection.projection is not None
    assert "input_tokens" in collection.projection


def test_usage_repository_validates_usage_and_timestamps() -> None:
    repository, _ = _repository()
    with pytest.raises(ValueError, match="Origem"):
        repository.record_usage(
            event_id="e",
            source="unknown",  # type: ignore[arg-type]
            model="m",
            input_tokens=1,
            output_tokens=1,
            status="completed",
        )
    for field, value in (
        ("event_id", " "),
        ("model", " "),
        ("input_tokens", True),
        ("input_tokens", -1),
        ("output_tokens", 1.5),
        ("item_count", -1),
    ):
        kwargs: dict[str, Any] = {
            "event_id": "e",
            "source": "lab",
            "model": "model",
            "input_tokens": 1,
            "output_tokens": 1,
            "item_count": 1,
            "status": "completed",
        }
        kwargs[field] = value
        with pytest.raises(ValueError):
            repository.record_usage(**kwargs)

    with pytest.raises(ValueError, match="timezone"):
        repository.record_usage(
            event_id="e",
            source="lab",
            model="model",
            input_tokens=None,
            output_tokens=None,
            status="error",
            timestamp=datetime(2026, 1, 1),
        )
    with pytest.raises(ValueError, match="timezone"):
        list(
            repository.iter_usage(
                started_from=datetime(2026, 1, 1),
                started_to=NOW,
            )
        )


def test_usage_repository_tolerates_database_errors_and_normalizes_metadata() -> None:
    repository, collection = _repository()
    collection.fail_writes = True
    repository.record_usage(
        event_id="e",
        source="title_generation",
        model="model",
        input_tokens=None,
        output_tokens=None,
        status="error",
    )
    assert "e" not in collection.documents

    collection.documents["__usage_metadata__"] = {
        "_id": "__usage_metadata__",
        "metering_started_at": datetime(2026, 1, 1),
    }
    assert repository.get_metering_started_at() == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )

    collection.documents.clear()
    before = datetime.now(timezone.utc)
    started_at = repository.get_metering_started_at()
    after = datetime.now(timezone.utc)
    assert before <= started_at <= after


def test_usage_context_and_safe_recording_select_explicit_context() -> None:
    repository, collection = _repository()
    assert current_usage_conversation_id() is None
    with bind_usage_conversation("background-conversation"):
        assert current_usage_conversation_id() == "background-conversation"
        record_usage_safely(
            repository,
            event_id="context-event",
            source="summary_generation",
            model="gpt-6-luna",
            input_tokens=12,
            output_tokens=4,
            status="completed",
        )
    assert current_usage_conversation_id() is None
    assert collection.documents["context-event"]["conversation_id"] == (
        "background-conversation"
    )

    record_usage_safely(
        None,
        event_id="ignored",
        source="lab",
        model="model",
        input_tokens=None,
        output_tokens=None,
        status="error",
    )
    record_usage_safely(
        repository,
        event_id="explicit-event",
        source="lab",
        model="model",
        input_tokens=1,
        output_tokens=2,
        status="completed",
        trace_id="explicit-trace",
        conversation_id="explicit-conversation",
    )
    assert collection.documents["explicit-event"]["trace_id"] == "explicit-trace"
    assert collection.documents["explicit-event"]["conversation_id"] == (
        "explicit-conversation"
    )

    def fail_recording(**_: Any) -> None:
        raise RuntimeError("best effort")

    repository.record_usage = fail_recording  # type: ignore[method-assign]
    record_usage_safely(
        repository,
        event_id="failed",
        source="lab",
        model="model",
        input_tokens=1,
        output_tokens=2,
        status="completed",
    )


def test_callback_handler_reads_generation_usage_and_error_callbacks() -> None:
    repository, collection = _repository()
    handler = AIUsageCallbackHandler(
        repository=repository,
        source="lab",
        model="gpt-6-luna",
    )
    run_id = uuid4()
    response = SimpleNamespace(
        generations=[
            [
                SimpleNamespace(
                    message=SimpleNamespace(
                        usage_metadata={"input_tokens": 7, "output_tokens": 3}
                    )
                )
            ]
        ],
        llm_output=None,
    )
    handler.on_llm_end(response, run_id=run_id)
    assert collection.documents[str(run_id)]["input_tokens"] == 7

    error_id = uuid4()
    handler.on_llm_error(RuntimeError("provider"), run_id=error_id)
    assert collection.documents[str(error_id)]["status"] == "error"

    assert AIUsageCallbackHandler._token_usage(
        SimpleNamespace(
            generations=[],
            llm_output={"token_usage": {"prompt_tokens": 4, "completion_tokens": 2}},
        )
    ) == (4, 2)
    assert AIUsageCallbackHandler._token_usage(
        SimpleNamespace(
            generations=[],
            llm_output={"usage": {"input_tokens": True, "output_tokens": -1}},
        )
    ) == (None, None)


def test_invoke_with_usage_supports_models_with_and_without_config() -> None:
    repository, collection = _repository()

    class ModelWithConfig:
        def invoke(self, value: str, config: dict[str, Any] | None = None) -> str:
            assert config is not None
            callback = config["callbacks"][0]
            callback.on_llm_end(
                SimpleNamespace(
                    generations=[],
                    llm_output={"usage": {"input_tokens": 2, "output_tokens": 1}},
                ),
                run_id=uuid4(),
            )
            return value.upper()

    class LegacyModel:
        def invoke(self, value: str) -> str:
            return value.upper()

    assert (
        invoke_with_usage(
            ModelWithConfig(),
            "hello",
            repository=repository,
            source="lab",
            model_name="gpt-6-luna",
        )
        == "HELLO"
    )
    assert (
        invoke_with_usage(
            LegacyModel(),
            "hello",
            repository=repository,
            source="lab",
            model_name="gpt-6-luna",
        )
        == "HELLO"
    )
    assert any(event.get("source") == "lab" for event in collection.documents.values())
