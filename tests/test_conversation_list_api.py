from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from src.api.controllers.conversation_list_controller import ConversationListController
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_list_controller,
)
from src.api.services.conversation_list_service import ConversationListService
from src.auth.models import AuthenticatedPrincipal
from src.main import create_app


class FakeConversationRepository:
    def __init__(self, conversations: list[dict[str, Any]]) -> None:
        self.conversations = conversations
        self.requested_email: str | None = None

    def list_ended_conversations(self, *, email: str) -> list[dict[str, Any]]:
        self.requested_email = email
        return self.conversations


def _client(
    conversations: list[dict[str, Any]],
) -> tuple[TestClient, Any, Any]:
    repository = FakeConversationRepository(conversations)
    controller = ConversationListController(ConversationListService(repository))
    app = create_app()
    app.dependency_overrides[get_conversation_list_controller] = lambda: controller
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(email="user-1", role_id=2)
    )
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
    assert repository.requested_email == "user-1"


def test_list_ended_conversations_returns_empty_list() -> None:
    client, app, _ = _client([])

    with client:
        response = client.get(
            "/api/v1/conversations/ended",
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"conversations": []}


def test_list_ended_conversations_uses_authenticated_email_without_query_identity() -> (
    None
):
    app = create_app()
    repository = FakeConversationRepository([])
    controller = ConversationListController(ConversationListService(repository))
    app.dependency_overrides[get_conversation_list_controller] = lambda: controller
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(email="verified@example.test", role_id=2)
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations/ended")

    assert response.status_code == 200
    assert repository.requested_email == "verified@example.test"


def test_user_id_query_does_not_override_authenticated_email() -> None:
    client, app, _ = _client([])

    with client:
        response = client.get(
            "/api/v1/conversations/ended",
            params={"user_id": "another-user"},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 200
