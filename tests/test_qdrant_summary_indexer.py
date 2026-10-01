from datetime import datetime, timezone
from typing import Any

from qdrant_client import models

from src.memory.contracts import ConversationSummarySnapshot, StoredMessage
from src.memory.qdrant_summary_indexer import QdrantSummaryIndexer


def _messages() -> list[StoredMessage]:
    return [
        StoredMessage(
            message_id="message-4",
            role="user",
            content="Question",
            created_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        )
    ]


class FakeQdrantClient:
    def __init__(self) -> None:
        self.exists = False
        self.payload: dict[str, Any] | None = None
        self.create_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs: Any) -> None:
        self.create_calls.append(kwargs)
        self.exists = True

    def upsert(self, **kwargs: Any) -> None:
        self.upsert_calls.append(kwargs)
        self.payload = kwargs["points"][0].payload

    def retrieve(self, **_: Any) -> list[Any]:
        if self.payload is None:
            return []
        return [type("Point", (), {"payload": self.payload})()]

    def delete(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)
        self.payload = None


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
        messages=_messages(),
        updated_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )

    indexer.upsert(snapshot)
    indexer.upsert(snapshot)

    assert len(client.create_calls) == 1
    assert client.create_calls[0]["vectors_config"].size == 2
    assert len(client.upsert_calls) == 1

    first_point = client.upsert_calls[0]["points"][0]
    assert isinstance(first_point, models.PointStruct)
    assert first_point.vector == [0.1, 0.2]
    assert first_point.payload == {
        "memory_type": "conversation_summary",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "status": "ended",
        "title": "Title",
        "summary": "Summary",
        "summary_version": 2,
        "summarized_through_message_id": "message-4",
        "updated_at": "2026-09-21T00:00:00+00:00",
    }


def test_read_and_delete_use_the_stable_conversation_point_id() -> None:
    client = FakeQdrantClient()
    indexer = QdrantSummaryIndexer(
        client=client,  # type: ignore[arg-type]
        embed_text=lambda _: [0.1],
        collection_name="conversation_summaries",
    )
    snapshot = ConversationSummarySnapshot(
        conversation_id="conversation-1",
        user_id="user-1",
        title=None,
        status="ended",
        summary="Summary",
        summary_version=1,
        summarized_through_message_id="message-4",
        messages=_messages(),
        updated_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )

    assert indexer.get("conversation-1") is None
    indexer.upsert(snapshot)
    assert indexer.get("conversation-1")["summary"] == "Summary"  # type: ignore[index]
    indexer.delete("conversation-1")
    indexer.delete("conversation-1")
    assert indexer.get("conversation-1") is None
    assert len(client.delete_calls) == 2


def test_upsert_does_not_regress_a_later_qdrant_watermark() -> None:
    client = FakeQdrantClient()
    indexer = QdrantSummaryIndexer(
        client=client,  # type: ignore[arg-type]
        embed_text=lambda _: [0.1],
        collection_name="conversation_summaries",
    )
    later = ConversationSummarySnapshot(
        conversation_id="conversation-1",
        user_id="user-1",
        title=None,
        status="ended",
        summary="Later summary",
        summary_version=2,
        summarized_through_message_id="message-4",
        messages=_messages(),
        updated_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    indexer.upsert(later)
    stale = later.model_copy(
        update={
            "summary": "Stale summary",
            "summary_version": 1,
            "summarized_through_message_id": "message-3",
            "messages": [
                StoredMessage(
                    message_id="message-3",
                    role="user",
                    content="Earlier",
                    created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
                ),
                *_messages(),
            ],
        }
    )
    indexer.upsert(stale)

    assert len(client.upsert_calls) == 1
    assert client.payload is not None
    assert client.payload["summary"] == "Later summary"
