"""Router node for the currently implemented agent capabilities."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from langchain_core.messages import AnyMessage, SystemMessage
from pydantic import ValidationError

from src.context.schemas import RouteDecision
from src.context.state import GraphState, RoutingDecision
from src.llm_factory import get_structured_model

from .router_prompt import ROUTER_SYSTEM_PROMPT


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


def route_router_state(
    state: GraphState,
    *,
    structured_model: Any,
) -> dict[str, Any]:
    """Route the current graph state using a structured router model."""

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
            reason="Nao foi possivel classificar a solicitacao com seguranca.",
        )

    return {
        "routing_decision": _normalize_decision(decision),
        "status": "in_progress",
    }


def create_router_node(
    model: Any | None = None,
) -> Callable[[GraphState], dict[str, Any]]:
    """Create a router node with optional model injection for tests."""

    structured_model = model or get_structured_model(RouteDecision)
    return partial(route_router_state, structured_model=structured_model)


router_node = create_router_node
