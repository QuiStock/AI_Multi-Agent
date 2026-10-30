from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from src.agents.router.executor import RouterExecutor
from src.agents.router.router_node import run_router_node
from src.graphs.contracts import RouteDecision
from src.graphs.state import RouteName as Route

pytestmark = pytest.mark.integration


class ScriptedRouterAgent:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    def invoke(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"structured_response": self.decision}


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
    decision = RouteDecision(route=route, reason="Classificação controlada.")
    executor = RouterExecutor(
        agent_factory=lambda **_: ScriptedRouterAgent(decision),
    )

    result = run_router_node(
        {
            "messages": [HumanMessage(content="Solicitação de teste.")],
            "status": "pending",
        },
        router=executor,
    )

    assert result["routing_decision"]["outcome"] == expected_outcome
