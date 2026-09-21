from datetime import datetime, timezone
from typing import Any

from qdrant_client import models

from src.memory.contracts import ConversationSummarySnapshot
from src.memory.qdrant_summary_indexer import QdrantSummaryIndexer


class FakeQdrantClient:
    def __init__(self) -> None:
        self.exists = False
        self.create_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs: Any) -> None:
        self.create_calls.append(kwargs)
        self.exists = True

    def upsert(self, **kwargs: Any) -> None:
        self.upsert_calls.append(kwargs)


def test_summary_upsert_uses_a_stable_point_and_versioned_payload() -> None:
    client = FakeQdrantClient()
    indexer = QdrantSummaryIndexer(
        client=client,  # type: ignore[arg-type]
        embed_text=lambda text: [0.1, 0.2] if text == "Summary" else [],
        collection_name="conversation_summaries",
    )
    snapshot = ConversationSummarySnapshot(
        conversation_id="conversation-1",
        user_id="user-1",
        title="Title",
        status="ended",
        summary="Summary",
        summary_version=2,
        summarized_through_message_id="message-4",
        messages=[],
        updated_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )

    indexer.upsert(snapshot)
    indexer.upsert(snapshot)

    assert len(client.create_calls) == 1
    assert client.create_calls[0]["vectors_config"].size == 2
    assert len(client.upsert_calls) == 2

    first_point = client.upsert_calls[0]["points"][0]
    second_point = client.upsert_calls[1]["points"][0]
    assert isinstance(first_point, models.PointStruct)
    assert first_point.id == second_point.id
    assert first_point.vector == [0.1, 0.2]
    assert first_point.payload == {
        "memory_type": "conversation_summary",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "status": "ended",
        "title": "Title",
        "summary": "Summary",
        "summary_version": 2,
        "updated_at": "2026-09-21T00:00:00+00:00",
    }
