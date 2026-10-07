from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.graphs.agent_graph import create_agent_graph
from src.guardrails.input import input_guardrail_node
from src.memory.checkpointer import create_local_checkpointer


class RecordingMessageService:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    def save_turn(self, **kwargs: Any) -> None:
        self.turns.append(kwargs)


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
        email: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        return []


class HistoricalContextEnricher:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def restore_messages(
        self,
        *,
        email: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        self.calls.append({"email": email, "conversation_id": conversation_id})
        return [
            HumanMessage(id="old:user", content="pergunta anterior"),
            AIMessage(id="old:assistant", content="resposta anterior"),
        ]


def _passed_input(state: dict[str, Any]) -> dict[str, Any]:
    return input_guardrail_node(
        state,
        validator=lambda _: {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
            "sanitized_message": "mensagem sanitizada",
            "pii_map": {"[PII]": "original"},
        },
    )


def _blocked_input(state: dict[str, Any]) -> dict[str, Any]:
    return input_guardrail_node(
        state,
        validator=lambda _: {
            "status": "blocked",
            "reason_code": "prompt_injection",
            "reason": "Bloqueado.",
            "redactions": [],
        },
    )


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
        "email": "user-1",
        "conversation_id": "conversation-1",
    }


def _user_message(request_id: str, content: str) -> HumanMessage:
    return HumanMessage(content=content, id=f"{request_id}:user")


def test_accepted_turn_persists_user_and_assistant_together() -> None:
    service = RecordingMessageService()
    result = _graph(service).invoke(
        {
            "request": _request("request-1"),
            "messages": [_user_message("request-1", "mensagem original")],
        }
    )

    assert service.turns == [
        {
            "conversation_id": "conversation-1",
            "email": "user-1",
            "request_id": "request-1",
            "sanitized_user_content": "mensagem sanitizada",
            "assistant_content": "Preciso de mais detalhes para continuar.",
            "consulted_agents": [],
            "sent_at": None,
        }
    ]
    assert [(message.id, message.type) for message in result["messages"]] == [
        ("request-1:user", "human"),
        ("request-1:assistant", "ai"),
    ]
    assert result["messages"][0].content == "mensagem sanitizada"
    assert result["pii_map"] == {}


def test_rejected_input_does_not_persist_any_message() -> None:
    service = RecordingMessageService()
    result = _graph(service, input_guardrail=_blocked_input).invoke(
        {
            "request": _request("request-2"),
            "messages": [_user_message("request-2", "mensagem bloqueada")],
        }
    )

    assert result["final_response"]["status"] == "rejected"
    assert all(message.type != "human" for message in result["messages"])
    assert service.turns == []


def test_memory_saver_keeps_messages_between_turns() -> None:
    service = RecordingMessageService()
    graph = _graph(service, checkpointer=create_local_checkpointer())
    config = {"configurable": {"thread_id": "conversation-1"}}

    graph.invoke(
        {
            "request": _request("request-1"),
            "messages": [_user_message("request-1", "primeira")],
        },
        config,
    )
    result = graph.invoke(
        {
            "request": _request("request-2"),
            "messages": [_user_message("request-2", "segunda")],
        },
        config,
    )

    assert [message.id for message in result["messages"]] == [
        "request-1:user",
        "request-1:assistant",
        "request-2:user",
        "request-2:assistant",
    ]
    assert [item["request_id"] for item in service.turns] == [
        "request-1",
        "request-2",
    ]


def test_resumption_restores_history_before_current_turn() -> None:
    service = RecordingMessageService()
    enricher = HistoricalContextEnricher()
    graph = _graph(service, context_enricher=enricher)
    request = _request("request-resume")
    request["is_resuming_conversation"] = True

    result = graph.invoke(
        {
            "request": request,
            "messages": [_user_message("request-resume", "pergunta atual")],
        }
    )

    assert [message.id for message in result["messages"]] == [
        "old:user",
        "old:assistant",
        "request-resume:user",
        "request-resume:assistant",
    ]
    assert service.turns[0]["sanitized_user_content"] == "mensagem sanitizada"
    assert enricher.calls == [{"email": "user-1", "conversation_id": "conversation-1"}]


def test_new_conversation_does_not_restore_any_history() -> None:
    service = RecordingMessageService()
    enricher = HistoricalContextEnricher()

    _graph(service, context_enricher=enricher).invoke(
        {
            "request": _request("request-new"),
            "messages": [_user_message("request-new", "pergunta nova")],
        }
    )

    assert enricher.calls == []
