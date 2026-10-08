from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from src.memory.contracts import (
    ConversationSummary,
    SummaryCandidate,
    SummarySearchRequest,
    VersionedConversationSummary,
)
from src.memory.get_summary_context import get_summary_context
from src.memory.mongo_repository import MongoConversationRepository
from src.memory.service import SummaryContextService, SummarySearchConfig


class FakeQdrant:
    def __init__(self, points: list[Any]) -> None:
        self.points = points
        self.query: dict[str, Any] | None = None
        self.scroll_query: dict[str, Any] | None = None

    def query_points(self, **query: Any) -> Any:
        self.query = query
        return SimpleNamespace(points=self.points)

    def collection_exists(self, _: str) -> bool:
        return True

    def create_payload_index(self, **_: Any) -> None:
        pass

    def scroll(self, **query: Any) -> Any:
        self.scroll_query = query
        return self.points, None


class FakeSummaryRepository:
    def __init__(
        self,
        *,
        summaries: dict[str, VersionedConversationSummary],
        recent: list[ConversationSummary],
    ) -> None:
        self.summaries = summaries
        self.recent = recent
        self.requested_ids: list[str] | None = None
        self.fallback_arguments: dict[str, Any] | None = None

    def get_ended_conversation_metadata_by_ids(
        self,
        *,
        email: str,
        conversation_ids: list[str],
    ) -> dict[str, VersionedConversationSummary]:
        self.requested_ids = conversation_ids
        return {
            conversation_id: summary
            for conversation_id, summary in self.summaries.items()
            if conversation_id in conversation_ids
        }


class FakeMongoCursor(list[dict[str, Any]]):
    def sort(self, order: list[tuple[str, int]]) -> FakeMongoCursor:
        self.sort_order = order
        return self

    def limit(self, limit: int) -> FakeMongoCursor:
        self.limit_value = limit
        return self


class FakeMongoCollection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.query_filter: dict[str, Any] | None = None
        self.last_projection: dict[str, int] | None = None

    def find(
        self,
        query_filter: dict[str, Any],
        projection: dict[str, int],
    ) -> FakeMongoCursor:
        self.query_filter = query_filter
        self.last_projection = projection
        return FakeMongoCursor(self.documents)


def _candidate(
    conversation_id: str,
    *,
    score: float,
    summary_version: int = 1,
) -> SummaryCandidate:
    return {
        "conversation_id": conversation_id,
        "title": "Past conversation",
        "summary": f"Summary for {conversation_id}.",
        "updated_at": "2026-07-25T06:03:52+00:00",
        "summary_version": summary_version,
        "summarized_through_message_id": "last-message",
        "score": score,
    }


def _qdrant_payload(candidate: SummaryCandidate) -> dict[str, Any]:
    return {
        **candidate,
        "email": "user-1",
        "memory_type": "conversation_summary",
        "status": "ended",
    }


def _versioned_summary(
    conversation_id: str,
    *,
    summary_version: int = 1,
    summary: str | None = None,
) -> VersionedConversationSummary:
    return {
        "conversation_id": conversation_id,
        "title": "Current Mongo title",
        "summary": summary or f"Authoritative summary for {conversation_id}.",
        "updated_at": "2026-07-25T06:03:52+00:00",
        "summary_version": summary_version,
    }


def _service(
    qdrant: FakeQdrant,
    repository: FakeSummaryRepository,
) -> SummaryContextService:
    return SummaryContextService(
        repository,  # type: ignore[arg-type]
        qdrant,  # type: ignore[arg-type]
        lambda _: [0.1, 0.2],
        SummarySearchConfig(collection_name="conversation_summaries"),
    )


def test_qdrant_search_filters_ended_user_summaries_and_reads_payload() -> None:
    qdrant = FakeQdrant(
        [
            SimpleNamespace(
                score=0.8,
                payload={
                    "conversation_id": "previous-1",
                    "email": "user-1",
                    "status": "ended",
                    "memory_type": "conversation_summary",
                    "title": "Past conversation",
                    "summary": "The user recorded a housing expense.",
                    "summary_version": 2,
                    "summarized_through_message_id": "last-message",
                    "updated_at": datetime(2026, 7, 25, tzinfo=timezone.utc),
                },
            )
        ]
    )
    query_texts: list[str] = []

    results = get_summary_context(
        request=SummarySearchRequest(
            email="user-1",
            conversation_id="current-1",
            query="O que comprei?",
            collection_name="conversation_summaries",
        ),
        embed_query=lambda text: query_texts.append(text) or [0.1, 0.2],
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    assert len(results) == 1
    assert results[0]["summary"] == "The user recorded a housing expense."
    assert results[0]["summary_version"] == 2
    assert results[0]["score"] == 0.8
    assert query_texts == ["O que comprei?"]
    assert qdrant.query is not None
    assert qdrant.query["limit"] == 3
    assert qdrant.query["score_threshold"] == 0.5
    filters = qdrant.query["query_filter"]
    assert {condition.key for condition in filters.must} == {
        "email",
        "memory_type",
        "status",
    }
    assert filters.must_not[0].key == "conversation_id"


def test_service_uses_qdrant_text_after_mongo_owner_status_validation() -> None:
    qdrant = FakeQdrant(
        [
            SimpleNamespace(
                payload=_qdrant_payload(_candidate("valid", score=0.8)),
                score=0.8,
            ),
            SimpleNamespace(
                payload=_qdrant_payload(_candidate("stale", score=0.7)),
                score=0.7,
            ),
            SimpleNamespace(
                payload=_qdrant_payload(_candidate("low", score=0.4)),
                score=0.4,
            ),
        ]
    )
    repository = FakeSummaryRepository(
        summaries={"valid": _versioned_summary("valid")},
        recent=[],
    )

    summaries = _service(qdrant, repository).get_context(
        "user-1",
        "current-1",
        "O que comprei?",
    )

    assert [summary["conversation_id"] for summary in summaries] == ["valid"]
    assert summaries[0]["summary"] == "Summary for valid."
    assert repository.requested_ids == ["valid", "stale"]
    assert repository.fallback_arguments is None
    selection = _service(qdrant, repository).search_context(
        email="user-1",
        conversation_id="current-1",
        query="O que comprei?",
    )
    assert selection["source"] == "semantic"


def test_service_falls_back_to_recent_qdrant_payload() -> None:
    qdrant = FakeQdrant(
        [
            SimpleNamespace(
                payload=_qdrant_payload(_candidate("low", score=0.4)),
                score=0.4,
            )
        ]
    )
    repository = FakeSummaryRepository(
        summaries={"low": _versioned_summary("low")}, recent=[]
    )

    summaries = _service(qdrant, repository).get_context(
        "user-1",
        "current-1",
        "O que comprei?",
    )

    assert summaries[0]["conversation_id"] == "low"
    assert summaries[0]["summary"] == "Summary for low."
    selection = _service(qdrant, repository).search_context(
        email="user-1",
        conversation_id="current-1",
        query="O que comprei?",
    )
    assert selection["source"] == "fallback"
    assert repository.requested_ids == ["low"]
    assert qdrant.scroll_query is not None
    assert qdrant.scroll_query["order_by"].key == "updated_at"
    assert qdrant.scroll_query["limit"] == 3


def test_mongo_owner_status_validation_never_projects_summary_fields() -> None:
    collection = FakeMongoCollection(
        [
            {
                "_id": "recent-1",
                "title": "Recent chat",
                "updated_at": datetime(2026, 7, 25, tzinfo=timezone.utc),
            }
        ]
    )
    repository = MongoConversationRepository(collection)  # type: ignore[arg-type]

    summaries = repository.get_ended_conversation_metadata_by_ids(
        email="user-1",
        conversation_ids=["recent-1"],
    )

    assert summaries["recent-1"]["conversation_id"] == "recent-1"
    assert collection.query_filter == {
        "_id": {"$in": ["recent-1"]},
        "email": "user-1",
        "status": "ended",
    }
    assert "summary" not in collection.last_projection


def test_mongo_candidate_validation_returns_metadata_without_summary() -> None:
    collection = FakeMongoCollection(
        [
            {
                "_id": "previous-1",
                "title": "Mongo title",
                "updated_at": datetime(2026, 7, 25, tzinfo=timezone.utc),
            }
        ]
    )
    repository = MongoConversationRepository(collection)  # type: ignore[arg-type]

    summaries = repository.get_ended_conversation_metadata_by_ids(
        email="user-1",
        conversation_ids=["previous-1"],
    )

    assert summaries == {
        "previous-1": {
            "conversation_id": "previous-1",
            "title": "Mongo title",
            "updated_at": "2026-07-25T00:00:00+00:00",
        }
    }
    assert collection.query_filter == {
        "_id": {"$in": ["previous-1"]},
        "email": "user-1",
        "status": "ended",
    }
