from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.memory.contracts import SummaryCommit
from src.memory.mongo_repository import (
    ConversationNotEndedError,
    ConversationNotFoundError,
    MongoConversationRepository,
)


def _mongo_document() -> dict[str, object]:
    return {
        "_id": "conversation-1",
        "user_id": "user-1",
        "title": "Title",
        "status": "ended",
        "summary": "Previous summary",
        "summary_version": 2,
        "summarized_through_message_id": "m1",
        "messages": [
            {
                "message_id": "m1",
                "role": "user",
                "content": "Question",
                "created_at": datetime(2026, 9, 20),
            }
        ],
        "updated_at": datetime(2026, 9, 20),
    }


def test_summary_snapshot_scopes_by_owner_and_normalizes_mongo_dates() -> None:
    collection = Mock()
    collection.find_one.return_value = _mongo_document()
    repository = MongoConversationRepository(collection)

    snapshot = repository.get_summary_snapshot(
        conversation_id="conversation-1",
        user_id="user-1",
    )

    assert collection.find_one.call_args.args[0] == {
        "_id": "conversation-1",
        "user_id": "user-1",
    }
    assert snapshot.summary == "Previous summary"
    assert snapshot.summary_version == 2
    assert snapshot.summarized_through_message_id == "m1"
    assert snapshot.messages[0].created_at.tzinfo == timezone.utc
    assert snapshot.updated_at.tzinfo == timezone.utc


def test_mark_ended_updates_only_an_active_owned_conversation() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(matched_count=1)
    repository = MongoConversationRepository(collection)
    ended_at = datetime(2026, 9, 21, tzinfo=timezone.utc)

    repository.mark_ended(
        conversation_id="conversation-1",
        user_id="user-1",
        ended_at=ended_at,
    )

    assert collection.update_one.call_args.args[0] == {
        "_id": "conversation-1",
        "user_id": "user-1",
        "status": "active",
    }
    assert collection.update_one.call_args.args[1] == {
        "$set": {"status": "ended", "ended_at": ended_at}
    }


def test_resume_reopens_owned_conversation_and_returns_ordered_message_ids() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(matched_count=1)
    collection.find_one.return_value = {
        "messages": [
            {
                "message_id": "m2",
                "role": "assistant",
                "content": "Second",
                "created_at": datetime(2026, 9, 20, 12, 1),
            },
            {
                "message_id": "m1",
                "role": "user",
                "content": "First",
                "created_at": datetime(2026, 9, 20, 12, 0),
            },
        ]
    }
    repository = MongoConversationRepository(collection)
    resumed_at = datetime(2026, 9, 21, tzinfo=timezone.utc)

    messages = repository.resume_conversation(
        conversation_id="conversation-1",
        user_id="user-1",
        resumed_at=resumed_at,
    )

    assert collection.update_one.call_args.args[0] == {
        "_id": "conversation-1",
        "user_id": "user-1",
        "status": "ended",
    }
    assert collection.update_one.call_args.args[1] == {
        "$set": {"status": "active", "ended_at": None, "updated_at": resumed_at}
    }
    assert [message.message_id for message in messages] == ["m1", "m2"]
    assert all(message.created_at.tzinfo == timezone.utc for message in messages)


def test_resume_rejects_other_user_and_already_active_conversations() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(matched_count=0)
    collection.find_one.return_value = None
    repository = MongoConversationRepository(collection)

    with pytest.raises(ConversationNotFoundError):
        repository.resume_conversation(
            conversation_id="conversation-1",
            user_id="other-user",
            resumed_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        )

    collection.find_one.return_value = {"status": "active"}
    with pytest.raises(ConversationNotEndedError):
        repository.resume_conversation(
            conversation_id="conversation-1",
            user_id="user-1",
            resumed_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        )


def test_list_ended_conversations_only_queries_authenticated_user() -> None:
    collection = Mock()
    cursor = Mock()
    cursor.sort.return_value = [
        {
            "_id": "conversation-1",
            "title": "Earlier session",
            "updated_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        }
    ]
    collection.find.return_value = cursor
    repository = MongoConversationRepository(collection)

    result = repository.list_ended_conversations(user_id="user-1")

    assert collection.find.call_args.args[0] == {
        "user_id": "user-1",
        "status": "ended",
    }
    assert cursor.sort.call_args.args[0] == [
        ("updated_at", -1),
        ("_id", -1),
    ]
    assert result == [
        {
            "conversation_id": "conversation-1",
            "title": "Earlier session",
            "updated_at": "2026-09-20T00:00:00+00:00",
        }
    ]


def test_summary_commit_checks_version_and_message_boundary() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(modified_count=1)
    repository = MongoConversationRepository(collection)

    saved = repository.save_summary_if_current(
        SummaryCommit(
            conversation_id="conversation-1",
            user_id="user-1",
            expected_summary_version=2,
            expected_message_id="m1",
            summary="Updated summary",
            summarized_through_message_id="m2",
        )
    )

    query, update = collection.update_one.call_args.args
    assert query == {
        "_id": "conversation-1",
        "user_id": "user-1",
        "status": "ended",
        "summary_version": 2,
        "summarized_through_message_id": "m1",
    }
    assert update == {
        "$set": {
            "summary": "Updated summary",
            "summary_version": 3,
            "summarized_through_message_id": "m2",
        }
    }
    assert saved is True


def test_title_commit_requires_missing_title_and_current_summary_version() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(modified_count=1)
    repository = MongoConversationRepository(collection)

    saved = repository.save_title_if_missing(
        conversation_id="conversation-1",
        user_id="user-1",
        expected_summary_version=2,
        title="Conversation title",
    )

    query, update = collection.update_one.call_args.args
    assert query == {
        "_id": "conversation-1",
        "user_id": "user-1",
        "status": "ended",
        "summary_version": 2,
        "$or": [{"title": None}, {"title": {"$exists": False}}],
    }
    assert update == {"$set": {"title": "Conversation title"}}
    assert saved is True
