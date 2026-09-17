from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from src.graphs.state import (
    FAQResult,
    GraphState,
    JudgeResult,
    ResponseDraft,
    RoutingDecision,
)

GraphUpdate = GraphState
GraphNode = Callable[[GraphState], GraphUpdate]


class RouterExecutorPort(Protocol):
    def invoke(
        self,
        messages: Sequence[AnyMessage],
    ) -> RoutingDecision: ...


class FAQExecutorPort(Protocol):
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


class CompilerExecutorPort(Protocol):
    def invoke(self, state: GraphState) -> ResponseDraft: ...


def sanitized_state(state: GraphState) -> GraphState:
    request = state.get("request", {})
    sanitized = request.get("sanitized_message")

    if not sanitized:
        return state

    messages = list(state.get("messages", []))

    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            messages[index] = HumanMessage(
                content=sanitized,
                id=messages[index].id,
            )
            break
    return {
        **state,
        "messages": messages,
    }


def run_router_node(
    state: GraphState,
    *,
    router: RouterExecutorPort,
) -> GraphUpdate:
    current_state = sanitized_state(state)

    return {
        "routing_decision": router.invoke(
            current_state.get("messages", []),
        ),
        "status": "in_progress",
    }


def run_faq_node(
    state: GraphState,
    *,
    executor: FAQExecutorPort,
) -> GraphUpdate:
    current_state = sanitized_state(state)
    result = executor.invoke(
        {
            "messages": current_state.get("messages", []),
        }
    )

    messages: list[AnyMessage] = result.get(
        "messages",
        [],
    )

    answer = next(
        (
            str(message.content).strip()
            for message in reversed(messages)
            if isinstance(message, AIMessage) and str(message.content).strip()
        ),
        "",
    )

    faq_result: FAQResult = {
        "status": "success" if answer else "unavailable",
        "answer": answer,
        "citation_ids": [],
    }

    return {
        "agent_results": {
            "faq": faq_result,
        }
    }


def run_judge_node(state: GraphState, *, judge: Any) -> GraphUpdate:
    result = judge.invoke(
        {
            "agent_results": state.get(
                "agent_results",
                {},
            ),
            "evidences": state.get(
                "evidences",
                [],
            ),
        }
    )

    judge_result: JudgeResult = result

    return {
        "agent_results": {
            "judge": judge_result,
        },
    }


def run_compiler_node(
    state: GraphState,
    *,
    compiler: CompilerExecutorPort,
) -> GraphUpdate:
    result = compiler.invoke(state)

    return {
        "response_draft": result,
    }


def run_context_enrichment_node(
    state: GraphState,
) -> GraphUpdate:
    # No MVP, não carrega memória.
    # Futuramente, este ponto poderá receber MemoryService.
    return {}


def run_output_guardrail_node(
    state: GraphState,
    *,
    guardrail: GraphNode,
) -> GraphUpdate:
    return guardrail(state)
