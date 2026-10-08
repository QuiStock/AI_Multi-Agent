"""Shared state for the initial LangGraph routing flow."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

RoutingOutcome = Literal[
    "dispatch",
    "clarification_required",
    "out_of_scope",
]
RouteName = Literal["faq", "clarification_required", "out_of_scope"]
GuardrailStatus = Literal["passed", "blocked"]
TurnStatus = Literal["pending", "in_progress", "completed", "failed"]
AgentStatus = Literal["success", "unavailable", "error"]
ResponseStatus = Literal[
    "success",
    "clarification_required",
    "out_of_scope",
    "rejected",
    "unavailable",
    "error",
]


class AgentOutput(TypedDict):
    """Normalized output produced by a specialized agent."""

    content: str
    status: AgentStatus


def merge_agent_outputs(
    current: list[AgentOutput], update: list[AgentOutput]
) -> list[AgentOutput]:
    """Accumulate outputs from specialized agents in the shared state."""

    return [*current, *update]


class RoutingDecision(TypedDict):
    """Decision produced by the router for currently active capabilities."""

    route: RouteName
    target_agent: str | None
    outcome: RoutingOutcome
    reason: str


class InputGuardrail(TypedDict):
    """Result produced before the router is allowed to run."""

    status: GuardrailStatus
    reason: str


class AgentValidation(TypedDict):
    """Validation summary produced by the compiler for agent outputs."""

    status: Literal["passed", "blocked", "needs_revision"]
    reason: str


class OutputGuardrail(TypedDict):
    """Reserved contract for the output guardrail phase."""

    status: GuardrailStatus
    reason: str
    violations: list[str]


class Response(TypedDict):
    """User-facing result produced after routing and agent execution."""

    content: str
    status: ResponseStatus


class GraphState(TypedDict, total=False):
    """State shared by nodes in the initial sequential routing graph.

    Nodes should return partial updates instead of rebuilding the complete
    state. ``messages`` and ``agent_outputs`` are append-only channels; the
    other fields use LangGraph's default overwrite behavior.
    """

    session_id: str
    turn_id: str
    correlation_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    input_guardrail: InputGuardrail
    routing_decision: RoutingDecision
    agent_outputs: Annotated[list[AgentOutput], merge_agent_outputs]
    validation: AgentValidation
    output_guardrail: OutputGuardrail
    final_response: Response
    status: TurnStatus
    error: str
