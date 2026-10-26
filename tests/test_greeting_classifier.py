from __future__ import annotations

from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage

from src.graphs.agent_graph import create_agent_graph
from src.graphs.contracts import GreetingDecision
from src.graphs.state import RoutingDecision
from src.guardrails.greeting import (
    GREETING_RESPONSE,
    MAX_GREETING_CLASSIFIER_CHARS,
    GreetingGuardrail,
)


def _messages(content: str) -> list[AnyMessage]:
    return [HumanMessage(content=content)]


class FakeGreetingModel:
    def __init__(self, category: str) -> None:
        self.category = category
        self.calls: list[list[AnyMessage]] = []

    def invoke(self, messages: list[AnyMessage]) -> GreetingDecision:
        self.calls.append(messages)
        return GreetingDecision(category=self.category)


def test_greeting_classifier_uses_a_separate_structured_llm_contract() -> None:
    model = FakeGreetingModel("greeting_only")
    classifier = GreetingGuardrail(model=model)

    result = classifier.invoke(_messages("Olá"))

    assert result.category == "greeting_only"
    assert len(model.calls) == 1
    assert model.calls[0][-1].content == "Olá"


def test_greeting_classifier_falls_through_for_long_messages_without_llm_call() -> None:
    model = FakeGreetingModel("greeting_only")
    classifier = GreetingGuardrail(model=model)

    result = classifier.invoke(_messages("x" * (MAX_GREETING_CLASSIFIER_CHARS + 1)))

    assert result.category == "normal_request"
    assert model.calls == []


def test_greeting_classifier_falls_through_when_model_returns_normal_request() -> None:
    classifier = GreetingGuardrail(model=FakeGreetingModel("normal_request"))

    result = classifier.invoke(_messages("Olá, como funciona o processo?"))

    assert result.category == "normal_request"


class FailingRouter:
    def invoke(
        self,
        _: list[AnyMessage],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        raise AssertionError("saudação não deve chegar ao router")


class EmptyContext:
    def restore_messages(self, *, email: str, conversation_id: str) -> list[AnyMessage]:
        raise AssertionError("saudação nova não deve restaurar contexto")


class RecordingMessageService:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    def save_turn(self, **kwargs: Any) -> None:
        self.turns.append(kwargs)


def _passed_input(state: dict[str, Any]) -> dict[str, Any]:
    message = state["messages"][-1]
    return {
        "input_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Aprovado.",
            "redactions": [],
            "sanitized_message": message.content,
        },
        "messages": [HumanMessage(content=message.content, id=message.id)],
        "status": "in_progress",
    }


def _output_guardrail(state: dict[str, Any]) -> dict[str, Any]:
    response = state["final_response"]
    return {
        "output_guardrail": {
            "status": "passed",
            "reason_code": "approved",
            "reason": "Resposta fixa aprovada.",
            "violations": [],
        },
        "final_response": response,
        "status": "in_progress",
    }


def test_graph_answers_greeting_from_guardrail_without_invoking_router() -> None:
    message_service = RecordingMessageService()
    graph = create_agent_graph(
        input_guardrail=_passed_input,
        greeting_guardrail=GreetingGuardrail(model=FakeGreetingModel("greeting_only")),
        router=FailingRouter(),
        capabilities={},
        judge=object(),
        compiler=object(),
        output_guardrail=_output_guardrail,
        context_enricher=EmptyContext(),
        message_service=message_service,
    )

    result = graph.invoke(
        {
            "request": {
                "request_id": "request-1",
                "email": "user-1",
                "conversation_id": "conversation-1",
            },
            "messages": [HumanMessage(content="Olá", id="request-1:user")],
        }
    )

    assert result["greeting_classification"]["category"] == "greeting_only"
    assert result["final_response"] == {
        "content": GREETING_RESPONSE,
        "status": "success",
    }
    assert "output_guardrail" not in result
    assert message_service.turns[0]["sanitized_user_content"] == "Olá"
    assert message_service.turns[0]["consulted_agents"] == []
