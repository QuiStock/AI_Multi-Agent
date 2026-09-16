from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from src.graphs.state import GraphState, RouteName


def decide_after_input_guardrail(
        state: GraphState,
)-> Literal["context_enrichment", "input_rejected"]:
    guardrail = state.get("input_guardrail")

    if guardrail and guardrail["status"] == "passed":
        return "context_enrichment"

    return "input_rejected"

def decide_after_router(
    state: GraphState,
    *,
    active_routes: Collection[RouteName],
)-> str:
    decision = state.get("routing_decision")

    if not decision:
        return "out_of_scope"

    if decision["outcome"] == "clarification_required":
        return "clarification_required"

    route = decision["route"]

    if route in active_routes:
        return route
    
    return "out_of_scope"

def decide_after_judge(
        state: GraphState
)-> Literal["compiler", "judge_blocked"]:
    judge_result = state.get("agent_results", {}).get("judge")

    if (
        judge_result
        and judge_result["status"] == "approved"
    ):
        return "compiler"

    return "judge_blocked"

def decide_after_output_guardrail(
        state: GraphState
)-> Literal["finalize_output"]:
    return "finalize_output"
