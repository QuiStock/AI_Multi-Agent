from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.router.router_node import create_router_node
from src.context.schemas import RouteDecision


class FakeRouterModel:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def invoke(self, messages: list[Any]) -> RouteDecision:
        return self.decision


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


def test_router_keeps_clarification_as_controlled_route() -> None:
    node = create_router_node(
        FakeRouterModel(
            RouteDecision(
                route="clarification_required",
                reason="Falta especificar a informação desejada.",
            )
        )
    )

    result = node(_state("Pode me ajudar?"))

    assert result["routing_decision"]["outcome"] == "clarification_required"
    assert result["routing_decision"]["target_agent"] is None


def test_router_keeps_out_of_scope_as_controlled_route() -> None:
    node = create_router_node(
        FakeRouterModel(
            RouteDecision(
                route="out_of_scope",
                reason="A solicitação não pertence à capacidade ativa.",
            )
        )
    )

    result = node(_state("Quais produtos devo promover?"))

    assert result["routing_decision"]["outcome"] == "out_of_scope"
    assert result["routing_decision"]["target_agent"] is None


def test_invalid_router_output_falls_back_to_clarification() -> None:
    class InvalidRouterModel:
        def invoke(self, messages: list[Any]) -> dict[str, str]:
            return {}

    node = create_router_node(InvalidRouterModel())

    result = node(_state("Pode verificar isso?"))

    assert result["routing_decision"]["outcome"] == "clarification_required"
