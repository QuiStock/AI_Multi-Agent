from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.graphs.agent_graph import create_agent_graph
from src.memory.checkpointer import create_local_checkpointer


class RecordingMessageService:
    def __init__(self) -> None:
        self.user_messages: list[dict[str, Any]] = []
        self.assistant_messages: list[dict[str, Any]] = []

    def save_user_message(self, **kwargs: Any) -> bool:
        self.user_messages.append(kwargs)
        return True

    def save_assistant_message(self, **kwargs: Any) -> bool:
        self.assistant_messages.append(kwargs)
        return True


class ClarificationRouter:
    def invoke(
        self,
        _: list[AnyMessage],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "route": "clarification_required",
            "target_agent": None,
            "outcome": "clarification_required",
            "reason": "A pergunta precisa de mais detalhes.",
        }


class EmptyContextEnricher:
    def restore_messages(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        return []


class HistoricalContextEnricher:
    def restore_messages(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        return [
            HumanMessage(id="old:user", content="pergunta anterior"),
            AIMessage(id="old:assistant", content="resposta anterior"),
        ]


def _passed_input(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
        }
    }


def _blocked_input(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_guardrail": {
            "status": "blocked",
            "reason_code": "prompt_injection",
            "reason": "Bloqueado.",
            "redactions": [],
        }
    }


def _graph(
    message_service: RecordingMessageService,
    *,
    input_guardrail: Any = _passed_input,
    checkpointer: Any = None,
    context_enricher: Any = None,
) -> Any:
    return create_agent_graph(
        input_guardrail=input_guardrail,
        router=ClarificationRouter(),
        capabilities={},
        judge=object(),  # The clarification route does not invoke the judge.
        compiler=object(),  # The clarification route does not invoke the compiler.
        output_guardrail=lambda _: {},
        context_enricher=context_enricher or EmptyContextEnricher(),
        message_service=message_service,
        checkpointer=checkpointer,
    )


def _request(request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "sanitized_message": "mensagem sanitizada",
    }


def test_accepted_turn_persists_user_and_assistant_messages() -> None:
    service = RecordingMessageService()
    result = _graph(service).invoke(
        {
            "request": _request("request-1"),
            "messages": [HumanMessage(content="mensagem original")],
        }
    )

    assert service.user_messages == [
        {
            "conversation_id": "conversation-1",
            "user_id": "user-1",
            "request_id": "request-1",
            "sanitized_content": "mensagem sanitizada",
        }
    ]
    assert service.assistant_messages == [
        {
            "conversation_id": "conversation-1",
            "user_id": "user-1",
            "request_id": "request-1",
            "content": "Preciso de mais detalhes para continuar.",
            "consulted_agents": [],
        }
    ]
    assert [(message.id, message.type) for message in result["messages"]] == [
        ("request-1:user", "human"),
        ("request-1:assistant", "ai"),
    ]


def test_rejected_input_does_not_persist_any_message() -> None:
    service = RecordingMessageService()
    result = _graph(service, input_guardrail=_blocked_input).invoke(
        {
            "request": _request("request-2"),
            "messages": [HumanMessage(content="mensagem bloqueada")],
        }
    )

    assert result["final_response"]["status"] == "rejected"
    assert all(message.type != "human" for message in result["messages"])
    assert service.user_messages == []
    assert service.assistant_messages == []


def test_memory_saver_keeps_messages_between_turns() -> None:
    service = RecordingMessageService()
    graph = _graph(service, checkpointer=create_local_checkpointer())
    config = {"configurable": {"thread_id": "conversation-1"}}

    graph.invoke(
        {
            "request": _request("request-1"),
            "messages": [HumanMessage(content="primeira")],
        },
        config,
    )
    result = graph.invoke(
        {
            "request": _request("request-2"),
            "messages": [HumanMessage(content="segunda")],
        },
        config,
    )

    assert [message.id for message in result["messages"]] == [
        "request-1:user",
        "request-1:assistant",
        "request-2:user",
        "request-2:assistant",
    ]
    assert [item["request_id"] for item in service.user_messages] == [
        "request-1",
        "request-2",
    ]
    assert [item["request_id"] for item in service.assistant_messages] == [
        "request-1",
        "request-2",
    ]


def test_resumption_restores_history_before_current_turn() -> None:
    service = RecordingMessageService()
    graph = _graph(service, context_enricher=HistoricalContextEnricher())
    request = _request("request-resume")
    request["is_resuming_conversation"] = True

    result = graph.invoke(
        {
            "request": request,
            "messages": [HumanMessage(content="pergunta atual")],
        }
    )

    assert [message.id for message in result["messages"]] == [
        "old:user",
        "old:assistant",
        "request-resume:user",
        "request-resume:assistant",
    ]
    assert service.user_messages[0]["sanitized_content"] == "mensagem sanitizada"
