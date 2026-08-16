"""Router node for the currently implemented agent capabilities."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.messages import AnyMessage, SystemMessage
from pydantic import ValidationError

from src.context.schemas import RouteDecision
from src.context.state import GraphState, RoutingDecision
from src.models import get_chat_model

ROUTER_PROMPT_PATH = (
    Path(__file__).resolve().parents[3] / "prompts" / "router_system.md"
)
ROUTER_SYSTEM_PROMPT = ROUTER_PROMPT_PATH.read_text(encoding="utf-8")


def _normalize_decision(decision: RouteDecision) -> RoutingDecision:
    """Convert a model decision into the closed shared-state contract."""

    if decision.route == "faq":
        return {
            "route": "faq",
            "target_agent": "faq",
            "outcome": "dispatch",
            "reason": decision.reason,
        }

    if decision.route == "clarification_required":
        return {
            "route": "clarification_required",
            "target_agent": None,
            "outcome": "clarification_required",
            "reason": decision.reason,
        }

    return {
        "route": "out_of_scope",
        "target_agent": None,
        "outcome": "out_of_scope",
        "reason": decision.reason,
    }


def create_router_node(
    model: Any | None = None,
) -> Callable[[GraphState], dict[str, Any]]:
    """Create a router node with optional model injection for tests."""

    structured_model = model or get_chat_model().with_structured_output(RouteDecision)

    def route(state: GraphState) -> dict[str, Any]:
        messages: list[AnyMessage] = state.get("messages", [])
        try:
            decision = structured_model.invoke(
                [SystemMessage(content=ROUTER_SYSTEM_PROMPT), *messages]
            )
            if not isinstance(decision, RouteDecision):
                decision = RouteDecision.model_validate(decision)
        except ValidationError:
            decision = RouteDecision(
                route="clarification_required",
                reason="Não foi possível classificar a solicitação com segurança.",
            )

        return {
            "routing_decision": _normalize_decision(decision),
            "status": "in_progress",
        }

    return route


router_node = create_router_node
