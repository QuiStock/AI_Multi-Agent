from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from src.agents.router.executor import RouterExecutor
from src.graphs.adapters import run_router_node
from src.graphs.contracts import RouteDecision
from src.graphs.state import RouteName as Route

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
def test_router_adapter_calls_executor_for_active_route_contract(
    route: Route, expected_outcome: str
) -> None:
    executor = RouterExecutor(
        model=FakeRouterModel(
            RouteDecision(route=route, reason="Classificação controlada.")
        )
    )

    result = run_router_node(
        {
            "messages": [HumanMessage(content="Solicitação de teste.")],
            "status": "pending",
        },
        router=executor,
    )

    assert result["routing_decision"]["outcome"] == expected_outcome
