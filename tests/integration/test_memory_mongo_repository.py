from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.collection import Collection
from testcontainers.community.mongodb import MongoDbContainer

from src.memory.message_service import MemoryMessageService
from src.memory.mongo_repository import (
    ConversationClosedError,
    ConversationNotFoundError,
    MongoConversationRepository,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def mongo_client() -> Iterator[MongoClient]:
    with MongoDbContainer("mongo:7.0.7") as mongo:
        client = mongo.get_connection_client()
        try:
            yield client
        finally:
            client.close()


@pytest.fixture
def conversation_collection(mongo_client: MongoClient) -> Iterator[Collection]:
    database_name = f"memory_test_{uuid4().hex}"
    collection = mongo_client[database_name]["conversations"]
    try:
        yield collection
    finally:
        mongo_client.drop_database(database_name)


@pytest.fixture
def message_service(conversation_collection: Collection) -> MemoryMessageService:
    return MemoryMessageService(MongoConversationRepository(conversation_collection))


def _save_turn(
    service: MemoryMessageService,
    *,
    conversation_id: str = "conversation-1",
    email: str = "user-1",
    request_id: str = "request-1",
    user_content: str = "Question",
    assistant_content: str = "Answer",
    consulted_agents: list[str] | None = None,
    sent_at: datetime | None = None,
) -> None:
    service.save_turn(
        conversation_id=conversation_id,
        email=email,
        request_id=request_id,
        sanitized_user_content=user_content,
        assistant_content=assistant_content,
        consulted_agents=consulted_agents or [],
        sent_at=sent_at,
    )


def test_first_turn_creates_one_document_with_two_ordered_messages(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    sent_at = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)
    _save_turn(
        message_service,
        user_content="$2 milk",
        assistant_content="There are two cartons.",
        consulted_agents=["faq"],
        sent_at=sent_at,
    )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert "session_id" not in document
    assert document["email"] == "user-1"
    assert document["status"] == "active"
    assert document["title"] is None
    assert document["total_turns"] == 1
    assert [message["role"] for message in document["messages"]] == [
        "user",
        "assistant",
    ]
    assert [message["message_id"] for message in document["messages"]] == [
        "request-1:user",
        "request-1:assistant",
    ]
    assert document["messages"][0]["content"] == "$2 milk"
    assert document["messages"][1]["content"] == "There are two cartons."
    assert document["messages"][1]["consulted_agents"] == ["faq"]
    assert document["messages"][0]["created_at"].replace(tzinfo=timezone.utc) == sent_at
    assert document["updated_at"].replace(tzinfo=timezone.utc) >= sent_at


def test_repeated_turn_is_an_idempotent_noop(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    _save_turn(message_service)
    before = conversation_collection.find_one({"_id": "conversation-1"})

    _save_turn(message_service)

    after = conversation_collection.find_one({"_id": "conversation-1"})
    assert before is not None and after is not None
    assert after["messages"] == before["messages"]
    assert after["total_turns"] == 1
    assert after["updated_at"] == before["updated_at"]


def test_new_turn_appends_both_messages_and_increments_once(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    _save_turn(message_service)
    _save_turn(
        message_service,
        request_id="request-2",
        user_content="Follow-up",
        assistant_content="Follow-up answer",
    )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert [message["message_id"] for message in document["messages"]] == [
        "request-1:user",
        "request-1:assistant",
        "request-2:user",
        "request-2:assistant",
    ]
    assert document["total_turns"] == 2


def test_turn_is_scoped_to_its_user(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    _save_turn(message_service, email="owner")

    with pytest.raises(ConversationNotFoundError):
        _save_turn(
            message_service,
            email="another-user",
            request_id="request-2",
            user_content="Do not append",
        )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert document["email"] == "owner"
    assert len(document["messages"]) == 2


def test_ended_conversation_rejects_new_turn_but_accepts_retry(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    _save_turn(message_service)
    conversation_collection.update_one(
        {"_id": "conversation-1"},
        {"$set": {"status": "ended"}},
    )

    _save_turn(message_service)
    with pytest.raises(ConversationClosedError):
        _save_turn(
            message_service,
            request_id="request-2",
            user_content="New message",
        )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert len(document["messages"]) == 2
    assert document["total_turns"] == 1


def test_summary_snapshot_uses_qdrant_state_without_persisting_it_in_mongo(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    repository = MongoConversationRepository(conversation_collection)
    _save_turn(message_service)
    repository.mark_ended(
        conversation_id="conversation-1",
        email="user-1",
        ended_at=datetime.now(timezone.utc),
    )

    snapshot = repository.get_summary_snapshot(
        conversation_id="conversation-1",
        email="user-1",
        summary="Question and answer.",
        summary_version=1,
        summarized_through_message_id="request-1:assistant",
    )

    assert snapshot.status == "ended"
    assert [message.message_id for message in snapshot.messages] == [
        "request-1:user",
        "request-1:assistant",
    ]
    assert snapshot.summary == "Question and answer."
    assert snapshot.summary_version == 1
    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert not {
        "summary",
        "summary_version",
        "summarized_through_message_id",
    }.intersection(document)


def test_ended_conversation_is_listed_and_reopened_with_existing_history(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    repository = MongoConversationRepository(conversation_collection)
    _save_turn(message_service, conversation_id="conversation-resume")
    conversation_collection.update_one(
        {"_id": "conversation-resume"},
        {"$set": {"title": "Earlier session"}},
    )
    repository.mark_ended(
        conversation_id="conversation-resume",
        email="user-1",
        ended_at=datetime.now(timezone.utc),
    )

    listed = repository.list_ended_conversations(email="user-1")
    messages = repository.resume_conversation(
        conversation_id="conversation-resume",
        email="user-1",
        resumed_at=datetime.now(timezone.utc),
    )

    document = conversation_collection.find_one({"_id": "conversation-resume"})
    assert len(listed) == 1
    assert listed[0]["conversation_id"] == "conversation-resume"
    assert listed[0]["title"] == "Earlier session"
    assert [message.message_id for message in messages] == [
        "request-1:user",
        "request-1:assistant",
    ]
    assert document is not None
    assert document["status"] == "active"
    assert document["ended_at"] is None


def test_conversation_history_cannot_be_resumed_by_another_user(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    repository = MongoConversationRepository(conversation_collection)
    _save_turn(message_service, conversation_id="private-conversation", email="owner")
    repository.mark_ended(
        conversation_id="private-conversation",
        email="owner",
        ended_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ConversationNotFoundError):
        repository.resume_conversation(
            conversation_id="private-conversation",
            email="another-user",
            resumed_at=datetime.now(timezone.utc),
        )

    document = conversation_collection.find_one({"_id": "private-conversation"})
    assert document is not None
    assert document["email"] == "owner"
    assert document["status"] == "ended"
