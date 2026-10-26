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
    if any(error["agent"] == "router" for error in state.get("errors", [])):
        return "router_error"

    decision = state.get("routing_decision")

    if not decision:
        return "out_of_scope"

    if decision["outcome"] == "direct_response":
        return "judge"

    if decision["outcome"] == "clarification_required":
        return "clarification_required"

    route = decision["route"]

    if route in active_routes:
        return route

    return "out_of_scope"


def decide_after_faq(state: GraphState) -> str:
    result = state.get("agent_results", {}).get("faq", {})
    if result.get("status") in {"error", "unavailable"}:
        return "faq_controlled_response"
    if result.get("next_step", "continue") in {"continue", "clarification"}:
        return "compiler"
    return "faq_controlled_response"


def decide_after_compiler(state: GraphState) -> Literal["judge", "compiler_blocked"]:
    draft = state.get("response_draft")
    if draft and draft.get("status") == "blocked":
        return "compiler_blocked"
    return "judge"


def decide_after_judge(
    state: GraphState,
) -> Literal["output_guardrail", "prepare_judge_repair", "judge_blocked"]:
    judge_result = state.get("judge")

    if judge_result and judge_result["status"] == "approved":
        return "output_guardrail"

    draft = state.get("response_draft")
    if draft is not None and draft.get("origin") == "exact":
        return "judge_blocked"

    if (
        judge_result
        and judge_result["status"] == "insufficient_evidence"
        and judge_result.get("reason_code") not in {None, "missing_evidence"}
        and judge_result.get("repair_attempts", 0) < 1
    ):
        return "prepare_judge_repair"

    return "judge_blocked"


def decide_after_output_guardrail(state: GraphState) -> Literal["persist_turn"]:
    return "persist_turn"
