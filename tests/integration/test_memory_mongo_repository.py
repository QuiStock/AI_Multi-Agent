from collections.abc import Iterator
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.collection import Collection
from testcontainers.community.mongodb import MongoDbContainer

from src.memory.contracts import SummaryCommit
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


def test_first_user_message_creates_the_single_conversation_document(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    created = message_service.save_user_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="$2 milk",
    )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert created is True
    assert document is not None
    assert "session_id" not in document
    assert document["user_id"] == "user-1"
    assert document["status"] == "active"
    assert document["title"] is None
    assert document["summary"] is None
    assert document["summary_version"] == 0
    assert document["summarized_through_message_id"] is None
    assert document["total_turns"] == 0
    assert len(document["messages"]) == 1
    assert document["messages"][0]["content"] == "$2 milk"
    assert document["messages"][0]["role"] == "user"
    assert document["messages"][0]["message_id"] == "request-1:user"
    assert document["messages"][0]["created_at"].replace(
        tzinfo=timezone.utc
    ) == document["started_at"].replace(tzinfo=timezone.utc)


def test_assistant_reply_appends_and_increments_turns_once(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    message_service.save_user_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="Question",
    )

    inserted = message_service.save_assistant_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        content="$Answer",
        consulted_agents=["product_workflow"],
    )
    retry_inserted = message_service.save_assistant_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        content="$Answer",
        consulted_agents=["product_workflow"],
    )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert inserted is True
    assert retry_inserted is False
    assert document is not None
    assert [message["role"] for message in document["messages"]] == [
        "user",
        "assistant",
    ]
    assert document["messages"][1]["consulted_agents"] == ["product_workflow"]
    assert document["messages"][1]["content"] == "$Answer"
    assert document["total_turns"] == 1


def test_repeated_user_request_does_not_duplicate_message(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    arguments = {
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "request_id": "request-1",
        "sanitized_content": "Question",
    }

    assert message_service.save_user_message(**arguments) is True
    assert message_service.save_user_message(**arguments) is False

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert len(document["messages"]) == 1


def test_conversation_is_scoped_to_its_user(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    message_service.save_user_message(
        conversation_id="conversation-1",
        user_id="owner",
        request_id="request-1",
        sanitized_content="Private",
    )

    with pytest.raises(ConversationNotFoundError):
        message_service.save_user_message(
            conversation_id="conversation-1",
            user_id="another-user",
            request_id="request-2",
            sanitized_content="Do not append",
        )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert document["user_id"] == "owner"
    assert len(document["messages"]) == 1


def test_assistant_cannot_create_a_conversation(
    message_service: MemoryMessageService,
) -> None:
    with pytest.raises(ConversationNotFoundError):
        message_service.save_assistant_message(
            conversation_id="missing-conversation",
            user_id="user-1",
            request_id="request-1",
            content="Orphan response",
            consulted_agents=[],
        )


def test_ended_conversation_rejects_new_messages_but_accepts_retry(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    message_service.save_user_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="Question",
    )
    conversation_collection.update_one(
        {"_id": "conversation-1"},
        {"$set": {"status": "ended"}},
    )

    assert (
        message_service.save_user_message(
            conversation_id="conversation-1",
            user_id="user-1",
            request_id="request-1",
            sanitized_content="Question",
        )
        is False
    )
    with pytest.raises(ConversationClosedError):
        message_service.save_user_message(
            conversation_id="conversation-1",
            user_id="user-1",
            request_id="request-2",
            sanitized_content="New message",
        )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    assert len(document["messages"]) == 1


def test_stored_dates_are_utc_and_updated_at_tracks_latest_message(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    message_service.save_user_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="Question",
    )
    message_service.save_assistant_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        content="Answer",
        consulted_agents=[],
    )

    document = conversation_collection.find_one({"_id": "conversation-1"})
    assert document is not None
    user_time = document["messages"][0]["created_at"].replace(tzinfo=timezone.utc)
    assistant_time = document["messages"][1]["created_at"].replace(tzinfo=timezone.utc)
    updated_at = document["updated_at"].replace(tzinfo=timezone.utc)
    assert user_time.tzinfo == timezone.utc
    assert assistant_time >= user_time
    assert updated_at == max(user_time, assistant_time)


def test_summary_commit_advances_version_and_marker_only_once(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    repository = MongoConversationRepository(conversation_collection)
    message_service.save_user_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="Question",
    )
    message_service.save_assistant_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        content="Answer",
        consulted_agents=[],
    )

    repository.mark_ended(
        conversation_id="conversation-1",
        user_id="user-1",
        ended_at=datetime.now(timezone.utc),
    )
    snapshot = repository.get_summary_snapshot(
        conversation_id="conversation-1",
        user_id="user-1",
    )

    assert snapshot.status == "ended"
    assert [message.message_id for message in snapshot.messages] == [
        "request-1:user",
        "request-1:assistant",
    ]
    assert snapshot.messages[0].created_at.tzinfo == timezone.utc
    committed = repository.save_summary_if_current(
        SummaryCommit(
            conversation_id="conversation-1",
            user_id="user-1",
            expected_summary_version=snapshot.summary_version,
            expected_message_id=snapshot.summarized_through_message_id,
            summary="Question and answer.",
            summarized_through_message_id="request-1:assistant",
        )
    )
    stale_retry = repository.save_summary_if_current(
        SummaryCommit(
            conversation_id="conversation-1",
            user_id="user-1",
            expected_summary_version=snapshot.summary_version,
            expected_message_id=snapshot.summarized_through_message_id,
            summary="Duplicate summary.",
            summarized_through_message_id="request-1:assistant",
        )
    )
    updated = repository.get_summary_snapshot(
        conversation_id="conversation-1",
        user_id="user-1",
    )

    assert committed is True
    assert stale_retry is False
    assert updated.summary == "Question and answer."
    assert updated.summary_version == 1
    assert updated.summarized_through_message_id == "request-1:assistant"


def test_ended_conversation_is_listed_and_reopened_with_existing_history(
    conversation_collection: Collection,
    message_service: MemoryMessageService,
) -> None:
    repository = MongoConversationRepository(conversation_collection)
    message_service.save_user_message(
        conversation_id="conversation-resume",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="Question",
    )
    message_service.save_assistant_message(
        conversation_id="conversation-resume",
        user_id="user-1",
        request_id="request-1",
        content="Answer",
        consulted_agents=[],
    )
    conversation_collection.update_one(
        {"_id": "conversation-resume"},
        {"$set": {"title": "Earlier session"}},
    )
    repository.mark_ended(
        conversation_id="conversation-resume",
        user_id="user-1",
        ended_at=datetime.now(timezone.utc),
    )

    listed = repository.list_ended_conversations(user_id="user-1")
    messages = repository.resume_conversation(
        conversation_id="conversation-resume",
        user_id="user-1",
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
