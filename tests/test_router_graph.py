from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.router.router_node import create_router_node
from src.context.schemas import RouteDecision
from src.graphs.faq_graph import create_faq_graph


class FakeRouterModel:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def invoke(self, messages: list[Any]) -> RouteDecision:
        return self.decision


class FakeFAQAgent:
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "messages": [
                *state["messages"],
                AIMessage(content="A resposta veio da base documental."),
            ]
        }


def _state(message: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(content=message)], "status": "pending"}


def test_router_dispatches_only_to_active_faq_route() -> None:
    node = create_router_node(
        FakeRouterModel(RouteDecision(route="faq", reason="Pergunta documental."))
    )

    result = node(_state("Qual é a regra documentada?"))

    assert result["routing_decision"] == {
        "route": "faq",
        "target_agent": "faq",
        "outcome": "dispatch",
        "reason": "Pergunta documental.",
    }


def test_graph_returns_clarification_without_calling_faq() -> None:
    class FailingFAQAgent:
        def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
            raise AssertionError("FAQ não deveria ser chamado")

    graph = create_faq_graph(
        router_model=FakeRouterModel(
            RouteDecision(
                route="clarification_required",
                reason="Falta especificar a informação desejada.",
            )
        ),
        faq_agent=FailingFAQAgent(),
    )

    result = graph.invoke(_state("Pode me ajudar?"))

    assert result["response"]["status"] == "clarification_required"
    assert result["status"] == "completed"


def test_graph_treats_non_active_capability_as_out_of_scope() -> None:
    graph = create_faq_graph(
        router_model=FakeRouterModel(
            RouteDecision(
                route="out_of_scope",
                reason="A solicitação não pertence à capacidade ativa.",
            )
        ),
        faq_agent=FakeFAQAgent(),
    )

    result = graph.invoke(_state("Quais produtos devo promover?"))

    assert result["response"] == {
        "content": "Essa solicitação está fora do escopo atual.",
        "status": "out_of_scope",
    }


def test_invalid_router_output_falls_back_to_clarification() -> None:
    class InvalidRouterModel:
        def invoke(self, messages: list[Any]) -> dict[str, str]:
            return {}

    graph = create_faq_graph(
        router_model=InvalidRouterModel(),
        faq_agent=FakeFAQAgent(),
    )

    result = graph.invoke(_state("Pode verificar isso?"))

    assert result["response"]["status"] == "clarification_required"


def test_blocked_input_never_reaches_router() -> None:
    class FailingRouterModel:
        def invoke(self, messages: list[Any]) -> RouteDecision:
            raise AssertionError("Roteador não deveria ser chamado")

    graph = create_faq_graph(
        router_model=FailingRouterModel(),
        faq_agent=FakeFAQAgent(),
    )

    result = graph.invoke({"messages": [], "status": "pending"})

    assert result["response"]["status"] == "rejected"
