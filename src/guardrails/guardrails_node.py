from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage

from src.graphs.contracts import GreetingDecision
from src.graphs.state import GraphState, GreetingClassification
from src.guardrails.greeting import GREETING_RESPONSE

CONTROLLED_INPUT_RESPONSE = (
    "Desculpe, não posso tratar desse tipo de assunto no Quistock."
)
BLOCKED_INPUT_HISTORY_MARKER = "[ENTRADA_BLOQUEADA]"


class GreetingGuardrailPort(Protocol):
    def invoke(
        self,
        messages: Sequence[AnyMessage],
        *,
        request_context: Mapping[str, Any] | None = None,
    ) -> GreetingDecision: ...


def run_greeting_guardrail_node(
    state: GraphState,
    *,
    guardrail: GreetingGuardrailPort,
) -> GraphState:
    """Run the greeting guardrail before memory and model routing."""
    decision = guardrail.invoke(
        state.get("messages", []),
        request_context=state.get("request"),
    )
    classification: GreetingClassification = {
        "category": decision.category,
    }
    update: GraphState = {
        "greeting_classification": classification,
        "status": "in_progress",
    }
    if decision.category == "greeting_only":
        update["final_response"] = {
            "content": GREETING_RESPONSE,
            "status": "success",
        }
    return update


def run_output_guardrail_node(
    state: GraphState,
    *,
    guardrail: Callable[[GraphState], GraphState],
) -> GraphState:
    return guardrail(state)


def input_rejected_node(
    state: GraphState,
) -> GraphState:
    update: GraphState = {
        "final_response": {
            "content": CONTROLLED_INPUT_RESPONSE,
            "status": "rejected",
        },
        "status": "in_progress",
    }
    request = state.get("request")
    request_id = request.get("request_id") if request else None
    latest_human = next(
        (
            message
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage)
        ),
    )
    if latest_human is not None:
        message_id = (
            f"{request_id}:user"
            if isinstance(request_id, str) and request_id
            else latest_human.id
        )
        if message_id is not None:
            replacement: list[AnyMessage] = []
            if latest_human.id:
                replacement.append(cast(AnyMessage, RemoveMessage(id=latest_human.id)))
            replacement.append(
                HumanMessage(content=BLOCKED_INPUT_HISTORY_MARKER, id=message_id)
            )
            update["messages"] = replacement
    elif isinstance(request_id, str) and request_id:
        update["messages"] = [
            HumanMessage(
                content=BLOCKED_INPUT_HISTORY_MARKER,
                id=f"{request_id}:user",
            )
        ]
    return update
