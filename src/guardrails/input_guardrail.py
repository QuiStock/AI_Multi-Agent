"""Input guardrail boundary used before routing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage

from src.context.state import GraphState, InputGuardrail


def validate_input(state: GraphState) -> InputGuardrail:
    """Perform the basic input check and reserve the safety boundary.

    Domain-specific safety policies can be injected here without changing the
    router contract. An empty user message is blocked deterministically; valid
    messages are passed to the router.
    """

    messages = state.get("messages", [])
    latest_human = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
        ),
        None,
    )
    if latest_human is None or not str(latest_human.content).strip():
        return {"status": "blocked", "reason": "A mensagem do usuário está vazia."}

    return {"status": "passed", "reason": "Entrada aprovada pelo guardrail."}


def input_guardrail_node(
    state: GraphState,
    validator: Callable[[GraphState], InputGuardrail] = validate_input,
) -> dict[str, Any]:
    """Run the guardrail and write only its result to shared state."""

    result = validator(state)
    return {
        "input_guardrail": result,
        "status": "in_progress" if result["status"] == "passed" else "completed",
    }
