from __future__ import annotations

import json
from typing import Any

import pytest
from a2a.types import a2a_pb2
from fastapi import HTTPException
from google.protobuf.json_format import ParseDict
from langchain_core.messages import HumanMessage
from pymongo.errors import DuplicateKeyError

from src import config
from src.a2a_integration.external import ExternalA2AExecutor
from src.a2a_integration.inbound import _bearer, agent_card, router, send_message
from src.agents.judge.executor import JudgeExecutor
from src.api.schemas.conversation import ConversationResponse
from src.auth.models import AuthenticatedPrincipal


class FakeStore:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def insert_one(self, document: dict[str, Any]) -> None:
        if document["_id"] in self.documents:
            raise DuplicateKeyError("duplicate")
        self.documents[document["_id"]] = document

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return self.documents.get(query["_id"])

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        self.documents[query["_id"]].update(update["$set"])

    def delete_one(self, query: dict[str, Any]) -> None:
        self.documents.pop(query["_id"], None)


class FakeController:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> ConversationResponse:
        self.calls.append(kwargs)
        return ConversationResponse(
            conversation_id=kwargs["conversation_id"],
            request_id=kwargs["request_id"],
            response="Resposta do Quistock",
            status="success",
        )


def _setup(monkeypatch: Any) -> tuple[FakeStore, FakeController]:
    settings = config.Settings(
        _env_file=None,
        a2a_context_secret="test-context-secret",
        a2a_inbound_service_token="test-service-secret",
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    return FakeStore(), FakeController()


def _body(context_id: str, message_id: str, text: str) -> dict[str, Any]:
    return {
        "message": {
            "messageId": message_id,
            "contextId": context_id,
            "role": "ROLE_USER",
            "parts": [{"text": text}],
        }
    }


def _send(
    body: dict[str, Any],
    email: str,
    store: FakeStore,
    controller: FakeController,
) -> dict[str, Any]:
    response = send_message(
        body,
        AuthenticatedPrincipal(email=email, role_id=2),
        controller,
        store,
        None,
    )
    assert response.status_code == 200
    return json.loads(response.body)


def test_agent_card_advertises_rest_skills(monkeypatch: Any) -> None:
    _setup(monkeypatch)
    card = ParseDict(json.loads(agent_card().body), a2a_pb2.AgentCard())
    assert card.supported_interfaces[0].protocol_binding == "HTTP+JSON"
    assert {skill.id for skill in card.skills} == {
        "faq",
        "product_flow",
        "truck_information",
    }
    paths = {route.path for route in router.routes}
    assert "/a2a/message:send" in paths
    assert "/.well-known/agent-card.json" in paths


def test_a2a_business_route_requires_service_token() -> None:
    with pytest.raises(HTTPException) as exc:
        _bearer(None)
    assert exc.value.status_code == 401


def test_a2a_retries_are_cached_and_users_are_isolated(monkeypatch: Any) -> None:
    store, controller = _setup(monkeypatch)
    body = _body("shared-context", "message-1", "Olá")
    first = _send(body, "a@example.com", store, controller)
    again = _send(body, "a@example.com", store, controller)
    other = _send(body, "b@example.com", store, controller)
    assert first == again
    assert len(controller.calls) == 2
    assert (
        controller.calls[0]["conversation_id"] != controller.calls[1]["conversation_id"]
    )
    parsed = ParseDict(first, a2a_pb2.SendMessageResponse())
    assert parsed.message.parts[0].text == "Resposta do Quistock"
    assert other["message"]["contextId"] == "shared-context"


def test_a2a_rejects_message_id_reuse_with_new_text(monkeypatch: Any) -> None:
    store, controller = _setup(monkeypatch)
    _send(_body("c", "m", "Olá"), "a@example.com", store, controller)
    with pytest.raises(HTTPException) as exc:
        _send(_body("c", "m", "Outro texto"), "a@example.com", store, controller)
    assert exc.value.status_code == 409
    assert len(controller.calls) == 1


def test_first_message_without_context_id_is_idempotent(monkeypatch: Any) -> None:
    store, controller = _setup(monkeypatch)
    body = {
        "message": {
            "messageId": "first",
            "role": "ROLE_USER",
            "parts": [{"text": "Oi"}],
        }
    }
    first = _send(body, "a@example.com", store, controller)
    again = _send(body, "a@example.com", store, controller)
    assert first == again
    assert len(controller.calls) == 1


def test_external_mock_is_attributed_and_keeps_user_identity_local() -> None:
    executor = ExternalA2AExecutor(config.Settings(_env_file=None))
    result = executor.invoke(
        {
            "request": {
                "conversation_id": "c",
                "request_id": "r",
                "email": "private@example.com",
            },
            "messages": [HumanMessage(content="Qual caminhão?", id="r:user")],
            "routing_decision": {
                "route": "external_a2a",
                "target_agent": "external_a2a",
                "outcome": "dispatch",
                "reason": "caminhões",
                "peer_id": "truck_info_agent",
                "skill_id": "truck_specs",
            },
        }
    )
    assert result["evidences"][0]["metadata"]["mock"] == "true"
    assert "private@example.com" not in result["answer"]


def test_judge_rejects_unattributed_a2a_answer() -> None:
    judge = JudgeExecutor(model=object())
    result = judge.invoke(
        response_draft={
            "content": "A resposta é simulada.",
            "citations": ["a2a:1"],
            "status": "draft",
        },
        evidences=[
            {
                "evidence_id": "a2a:1",
                "source_type": "a2a_agent",
                "source_id": "1",
                "content": "Resposta simulada",
                "metadata": {"mock": "true"},
            }
        ],
    )
    assert result["error_code"] == "JUDGE_A2A_ATTRIBUTION_MISSING"
