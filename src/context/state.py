"""Shared state for the initial LangGraph routing flow."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, NotRequired, TypedDict

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


class Evidence(TypedDict):
    """Document evidence returned by the FAQ retrieval tool."""

    arquivo: str
    conteudo: str
    relevancia: float
    pagina: NotRequired[int]


class AgentOutput(TypedDict):
    """Normalized output produced by a specialized agent."""

    content: str
    status: AgentStatus


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


class Response(TypedDict):
    """User-facing result produced after routing and agent execution."""

    content: str
    status: ResponseStatus


class GraphState(TypedDict, total=False):
    """State shared by nodes in the initial sequential routing graph.

    Nodes should return partial updates instead of rebuilding the complete
    state. ``messages`` and ``evidence`` are append-only channels; the other
    fields use LangGraph's default overwrite behavior.
    """

    session_id: str
    turn_id: str
    correlation_id: str
    messages: Annotated[list[AnyMessage], add_messages]
    input_guardrail: InputGuardrail
    routing_decision: RoutingDecision
    agent_name: str
    agent_output: AgentOutput
    evidence: Annotated[list[Evidence], operator.add]
    compiled_response: Response
    response: Response
    status: TurnStatus
    error: str
    trace_id: NotRequired[str]
