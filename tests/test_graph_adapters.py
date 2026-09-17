from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.graphs.adapters import (
    run_compiler_node,
    run_faq_node,
    run_router_node,
)
from src.graphs.state import GraphState, ResponseDraft, RoutingDecision


class FakeRouterExecutor:
    def __init__(self) -> None:
        self.messages: Sequence[AnyMessage] | None = None

    def invoke(self, messages: Sequence[AnyMessage]) -> RoutingDecision:
        self.messages = messages
        return {
            "route": "faq",
            "target_agent": "faq",
            "outcome": "dispatch",
            "reason": "Pergunta documental.",
        }


class FakeFAQExecutor:
    def __init__(self) -> None:
        self.state: dict[str, Any] | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.state = state
        return {
            "messages": [
                *state["messages"],
                AIMessage(content="Resposta baseada na documentação."),
            ]
        }


class FakeCompilerExecutor:
    def __init__(self) -> None:
        self.state: GraphState | None = None

    def invoke(self, state: GraphState) -> ResponseDraft:
        self.state = state
        return {
            "content": "Resposta compilada.",
            "citations": ["faq-1"],
            "status": "draft",
        }


def test_router_adapter_sanitizes_state_before_calling_executor() -> None:
    executor = FakeRouterExecutor()
    state: GraphState = {
        "request": {
            "request_id": "req-1",
            "user_id": "user-1",
            "conversation_id": "conversation-1",
            "sanitized_message": "Mensagem sanitizada.",
        },
        "messages": [HumanMessage(content="Mensagem com dado sensível.")],
    }

    result = run_router_node(state, router=executor)

    assert executor.messages is not None
    assert executor.messages[-1].content == "Mensagem sanitizada."
    assert result["routing_decision"]["route"] == "faq"
    assert result["status"] == "in_progress"


def test_faq_adapter_calls_executor_and_normalizes_answer() -> None:
    executor = FakeFAQExecutor()
    state: GraphState = {
        "messages": [HumanMessage(content="Qual é a regra?")],
    }

    result = run_faq_node(state, executor=executor)

    assert executor.state is not None
    assert executor.state["messages"] == state["messages"]
    assert result["agent_results"]["faq"] == {
        "status": "success",
        "answer": "Resposta baseada na documentação.",
        "citation_ids": [],
    }


def test_compiler_adapter_forwards_canonical_state_to_executor() -> None:
    executor = FakeCompilerExecutor()
    state: GraphState = {
        "agent_results": {
            "faq": {
                "status": "success",
                "answer": "Resposta do FAQ.",
                "citation_ids": ["faq-1"],
            }
        }
    }

    result = run_compiler_node(state, compiler=executor)

    assert executor.state is state
    assert result["response_draft"] == {
        "content": "Resposta compilada.",
        "citations": ["faq-1"],
        "status": "draft",
    }
