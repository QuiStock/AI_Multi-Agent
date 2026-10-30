from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from src.api.controllers.conversation_history_controller import (
    ConversationHistoryController,
)
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_history_controller,
)
from src.api.services.conversation_history_service import ConversationHistoryService
from src.auth.models import AuthenticatedPrincipal
from src.main import create_app
from src.memory.contracts import ConversationHistory, StoredMessage
from src.memory.conversations.mongo_repository import (
    ConversationNotFoundError,
    MongoConversationRepository,
)

TIMESTAMP = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _message(message_id: str, role: str, content: str) -> StoredMessage:
    return StoredMessage(
        message_id=message_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=TIMESTAMP,
    )


class FakeHistoryRepository:
    def __init__(self, status: str = "active") -> None:
        self.status = status
        self.messages = [
            _message("1:user", "user", "Primeira pergunta"),
            _message("1:assistant", "assistant", "Primeira resposta").model_copy(
                update={"consulted_agents": ["faq"]}
            ),
        ]
        self.fail = False
        self.requested_email: str | None = None

    def get_history(self, *, conversation_id: str, email: str) -> ConversationHistory:
        self.requested_email = email
        if self.fail:
            raise ServerSelectionTimeoutError("database details must not leak")
        if conversation_id != "conversation-1" or email != "owner@example.test":
            raise ConversationNotFoundError(conversation_id)
        return ConversationHistory(
            conversation_id=conversation_id,
            title="Estoque",
            status=self.status,  # type: ignore[arg-type]
            messages=list(self.messages),
        )


def _client(repository: FakeHistoryRepository) -> tuple[TestClient, Any]:
    app = create_app()
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(
            user_id=42,
            email="owner@example.test",
            role_code="MANAGER",
            store_ids=(4,),
        )
    )
    app.dependency_overrides[get_conversation_history_controller] = lambda: (
        ConversationHistoryController(ConversationHistoryService(repository))  # type: ignore[arg-type]
    )
    return TestClient(app), app


@pytest.mark.parametrize("conversation_status", ["active", "ended"])
def test_get_history_returns_all_messages_for_active_or_ended_conversation(
    conversation_status: str,
) -> None:
    repository = FakeHistoryRepository(conversation_status)
    client, app = _client(repository)

    with client:
        response = client.get("/api/v1/conversations/conversation-1/messages")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "conversation-1",
        "title": "Estoque",
        "status": conversation_status,
        "messages": [
            {
                "message_id": "1:user",
                "role": "user",
                "content": "Primeira pergunta",
                "created_at": "2026-10-12T12:00:00Z",
            },
            {
                "message_id": "1:assistant",
                "role": "assistant",
                "content": "Primeira resposta",
                "created_at": "2026-10-12T12:00:00Z",
            },
        ],
    }
    assert repository.requested_email == "owner@example.test"
    assert repository.status == conversation_status


def test_new_messages_appear_after_existing_history() -> None:
    repository = FakeHistoryRepository()
    client, app = _client(repository)

    with client:
        first = client.get("/api/v1/conversations/conversation-1/messages")
        repository.messages.extend(
            [
                _message("2:user", "user", "Segunda pergunta"),
                _message("2:assistant", "assistant", "Segunda resposta"),
            ]
        )
        second = client.get("/api/v1/conversations/conversation-1/messages")

    app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 200
    assert [item["message_id"] for item in first.json()["messages"]] == [
        "1:user",
        "1:assistant",
    ]
    assert [item["message_id"] for item in second.json()["messages"]] == [
        "1:user",
        "1:assistant",
        "2:user",
        "2:assistant",
    ]


def test_missing_or_other_users_conversation_returns_404() -> None:
    repository = FakeHistoryRepository()
    client, app = _client(repository)

    with client:
        missing = client.get("/api/v1/conversations/another-conversation/messages")
        app.dependency_overrides[get_authenticated_principal] = lambda: (
            AuthenticatedPrincipal(
                user_id=99,
                email="other@example.test",
                role_code="EMPLOYEE",
                store_ids=(4,),
            )
        )
        other_owner = client.get("/api/v1/conversations/conversation-1/messages")

    app.dependency_overrides.clear()
    assert missing.status_code == other_owner.status_code == 404
    assert missing.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert other_owner.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_get_history_requires_bearer_token() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/conversations/conversation-1/messages")

    assert response.status_code == 401


def test_mongo_unavailable_returns_safe_503() -> None:
    repository = FakeHistoryRepository()
    repository.fail = True
    client, app = _client(repository)

    with client:
        response = client.get("/api/v1/conversations/conversation-1/messages")

    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONVERSATION_HISTORY_UNAVAILABLE"
    assert "database details" not in response.text


class FakeCollection:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.query: dict[str, Any] | None = None
        self.projection: dict[str, int] | None = None

    def find_one(
        self, query: dict[str, Any], projection: dict[str, int]
    ) -> dict[str, Any] | None:
        self.query = query
        self.projection = projection
        if (
            query["_id"] != self.document["_id"]
            or query["email"] != self.document["email"]
            or self.document["status"] not in query["status"]["$in"]
        ):
            return None
        return self.document


def test_repository_reads_owned_messages_in_stored_order_without_mutation() -> None:
    collection = FakeCollection(
        {
            "_id": "conversation-1",
            "email": "owner@example.test",
            "title": None,
            "status": "ended",
            "messages": [
                {
                    "message_id": "1:user",
                    "role": "user",
                    "content": "Pergunta",
                    "created_at": TIMESTAMP.replace(tzinfo=None),
                },
                {
                    "message_id": "1:assistant",
                    "role": "assistant",
                    "content": "Resposta",
                    "created_at": TIMESTAMP.replace(tzinfo=None),
                },
            ],
        }
    )
    repository = MongoConversationRepository(collection)  # type: ignore[arg-type]

    history = repository.get_history(
        conversation_id="conversation-1", email="owner@example.test"
    )

    assert collection.query == {
        "_id": "conversation-1",
        "email": "owner@example.test",
        "status": {"$in": ["active", "ended"]},
    }
    assert [message.message_id for message in history.messages] == [
        "1:user",
        "1:assistant",
    ]
    assert all(message.created_at.tzinfo == UTC for message in history.messages)
    assert collection.document["status"] == "ended"


def test_repository_rejects_other_owner_and_deleting_conversation() -> None:
    collection = FakeCollection(
        {
            "_id": "conversation-1",
            "email": "owner@example.test",
            "status": "deleting",
            "messages": [],
        }
    )
    repository = MongoConversationRepository(collection)  # type: ignore[arg-type]

    with pytest.raises(ConversationNotFoundError):
        repository.get_history(
            conversation_id="conversation-1", email="owner@example.test"
        )
    collection.document["status"] = "active"
    with pytest.raises(ConversationNotFoundError):
        repository.get_history(
            conversation_id="conversation-1", email="other@example.test"
        )
