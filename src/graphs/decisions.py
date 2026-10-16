from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from src.graphs.state import GraphState, RouteName


def decide_after_input_guardrail(
    state: GraphState,
) -> Literal["context_enrichment", "input_rejected"]:
    guardrail = state.get("input_guardrail")

    if guardrail and guardrail["status"] == "passed":
        return "context_enrichment"

    return "input_rejected"


def decide_after_router(
    state: GraphState,
    *,
    active_routes: Collection[RouteName],
) -> str:
    decision = state.get("routing_decision")

    if not decision:
        return "out_of_scope"

    if decision["outcome"] == "direct_response":
        return "persist_turn"

    if decision["outcome"] == "clarification_required":
        return "clarification_required"

    route = decision["route"]

    if route in active_routes:
        return route

    return "out_of_scope"


def decide_after_faq(state: GraphState) -> str:
    result = state.get("agent_results", {}).get("faq", {})
    if result.get("next_step", "continue") == "continue":
        return "compiler"
    return "faq_controlled_response"


def decide_after_judge(
    state: GraphState,
) -> Literal["output_guardrail", "prepare_judge_repair", "judge_blocked"]:
    judge_result = state.get("agent_results", {}).get("judge")

    if judge_result and judge_result["status"] == "approved":
        return "output_guardrail"

    if (
        judge_result
        and judge_result["status"] == "insufficient_evidence"
        and judge_result.get("reason_code") not in {None, "missing_evidence"}
        and state.get("repair_attempts", 0) < 1
    ):
        return "prepare_judge_repair"

    return "judge_blocked"


def decide_after_output_guardrail(state: GraphState) -> Literal["persist_turn"]:
    return "persist_turn"
