from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_graph
from src.main import create_app
from src.memory.mongo_repository import ConversationClosedError


class FakeGraph:
    def __init__(self, *, status: str = "success") -> None:
        self.status = status
        self.state: dict[str, Any] | None = None
        self.config: dict[str, Any] | None = None

    def invoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.state = state
        self.config = config
        return {
            "final_response": {
                "content": "Resposta do agente.",
                "status": self.status,
            }
        }


class FailingGraph(FakeGraph):
    def invoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise ConversationClosedError("conversation-1")


@pytest.fixture
def app_client():  # type: ignore[no-untyped-def]
    graph = FakeGraph()
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph
    with TestClient(app) as client:
        yield client, graph
    app.dependency_overrides.clear()


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": "user-1",
        "message": "Qual é a regra?",
        "sent_at": "2026-09-22T14:30:00-03:00",
        "is_resuming_conversation": False,
    }
    payload.update(overrides)
    return payload


def test_conversation_endpoint_invokes_graph_and_returns_metadata(app_client) -> None:
    client, graph = app_client

    response = client.post(
        "/api/v1/conversations/conversation-1/messages",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conversation-1"
    assert body["response"] == "Resposta do agente."
    assert body["status"] == "success"
    UUID(body["request_id"])

    assert graph.state is not None
    assert graph.state["request"]["user_id"] == "user-1"
    assert graph.state["request"]["sent_at"] == datetime(
        2026,
        9,
        22,
        17,
        30,
        tzinfo=timezone.utc,
    )
    assert graph.config == {
        "configurable": {
            "thread_id": "conversation-1",
        }
    }


def test_conversation_endpoint_propagates_resume_flag(app_client) -> None:
    client, graph = app_client

    response = client.post(
        "/api/v1/conversations/conversation-1/messages",
        json=_payload(is_resuming_conversation=True),
    )

    assert response.status_code == 200
    assert graph.state is not None
    assert graph.state["request"]["is_resuming_conversation"] is True
    assert graph.state["request"]["is_new_conversation"] is False


def test_conversation_endpoint_rejects_timestamp_without_timezone(app_client) -> None:
    client, _ = app_client

    response = client.post(
        "/api/v1/conversations/conversation-1/messages",
        json=_payload(sent_at="2026-09-22T14:30:00"),
    )

    assert response.status_code == 422


def test_conversation_endpoint_returns_controlled_input_rejection() -> None:
    graph = FakeGraph(status="rejected")
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: graph

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            json=_payload(),
        )

    app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["status"] == "rejected"


def test_conversation_endpoint_maps_closed_conversation_to_conflict() -> None:
    app = create_app()
    app.dependency_overrides[get_graph] = lambda: FailingGraph()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/conversations/conversation-1/messages",
            json=_payload(),
        )

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONVERSATION_STATE_CONFLICT"
