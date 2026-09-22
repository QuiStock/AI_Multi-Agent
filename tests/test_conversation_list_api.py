from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from src.api.controllers.conversation_list_controller import ConversationListController
from src.api.dependencies import get_conversation_list_controller
from src.api.services.conversation_list_service import ConversationListService
from src.main import create_app


class FakeConversationRepository:
    def __init__(self, conversations: list[dict[str, Any]]) -> None:
        self.conversations = conversations
        self.requested_user_id: str | None = None

    def list_ended_conversations(self, *, user_id: str) -> list[dict[str, Any]]:
        self.requested_user_id = user_id
        return self.conversations


def _client(
    conversations: list[dict[str, Any]],
) -> tuple[TestClient, Any, Any]:
    repository = FakeConversationRepository(conversations)
    controller = ConversationListController(ConversationListService(repository))
    app = create_app()
    app.dependency_overrides[get_conversation_list_controller] = lambda: controller
    return TestClient(app), app, repository


def test_list_ended_conversations_returns_metadata_and_null_title() -> None:
    client, app, repository = _client(
        [
            {
                "conversation_id": "conversation-2",
                "title": None,
                "updated_at": "2026-09-22T17:30:00+00:00",
            },
            {
                "conversation_id": "conversation-1",
                "title": "Dúvida sobre estoque",
                "updated_at": "2026-09-21T17:30:00+00:00",
            },
        ]
    )

    with client:
        response = client.get(
            "/api/v1/conversations/ended",
            params={"user_id": " user-1 "},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "conversations": [
            {
                "conversation_id": "conversation-2",
                "title": None,
                "updated_at": "2026-09-22T17:30:00+00:00",
            },
            {
                "conversation_id": "conversation-1",
                "title": "Dúvida sobre estoque",
                "updated_at": "2026-09-21T17:30:00+00:00",
            },
        ]
    }
    assert repository.requested_user_id == "user-1"


def test_list_ended_conversations_returns_empty_list() -> None:
    client, app, _ = _client([])

    with client:
        response = client.get(
            "/api/v1/conversations/ended",
            params={"user_id": "user-1"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"conversations": []}


def test_list_ended_conversations_requires_user_id() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations/ended")

    assert response.status_code == 422


def test_list_ended_conversations_rejects_blank_user_id() -> None:
    client, app, _ = _client([])

    with client:
        response = client.get(
            "/api/v1/conversations/ended",
            params={"user_id": "   "},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONVERSATION_LIST_REQUEST"
