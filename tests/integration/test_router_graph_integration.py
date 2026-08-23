from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from src.agents.router.router_node import create_router_node
from src.context.schemas import Route, RouteDecision

pytestmark = pytest.mark.integration


class FakeRouterModel:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def invoke(self, messages: list[Any]) -> RouteDecision:
        return self.decision


@pytest.mark.parametrize(
    ("route", "expected_outcome"),
    [
        ("faq", "dispatch"),
        ("clarification_required", "clarification_required"),
        ("out_of_scope", "out_of_scope"),
    ],
)
def test_router_node_handles_active_route_contract(
    route: Route, expected_outcome: str
) -> None:
    node = create_router_node(
        FakeRouterModel(RouteDecision(route=route, reason="Classificação controlada."))
    )

    result = node(
        {
            "messages": [HumanMessage(content="Solicitação de teste.")],
            "status": "pending",
        }
    )

    assert result["routing_decision"]["outcome"] == expected_outcome
