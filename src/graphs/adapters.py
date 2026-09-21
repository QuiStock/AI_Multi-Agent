from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
)

from src.graphs.state import (
    Evidence,
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
        *,
        request_context: Mapping[str, Any] | None = None,
    ) -> RoutingDecision: ...


class ConversationContextEnricherPort(Protocol):
    def restore_messages(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> list[AnyMessage]: ...


class FAQExecutorPort(Protocol):
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


class CompilerExecutorPort(Protocol):
    def invoke(self, state: GraphState) -> ResponseDraft: ...


class JudgeExecutorPort(Protocol):
    def invoke(
        self,
        *,
        response_draft: ResponseDraft | None,
        evidences: Sequence[Evidence],
    ) -> JudgeResult: ...


def sanitized_state(state: GraphState) -> GraphState:
    request = state.get("request", {})
    sanitized = request.get("sanitized_message")

    if not sanitized:
        return state

    messages = list(state.get("messages", []))

    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            request_id = request.get("request_id")
            message_id = (
                f"{request_id}:user"
                if isinstance(request_id, str) and request_id.strip()
                else messages[index].id
            )
            messages[index] = HumanMessage(
                content=sanitized,
                id=message_id,
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
            request_context=current_state.get("request"),
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


def run_judge_node(
    state: GraphState,
    *,
    judge: JudgeExecutorPort,
) -> GraphUpdate:
    try:
        judge_result = judge.invoke(
            response_draft=state.get("response_draft"),
            evidences=state.get("evidences", []),
        )
    except Exception:
        judge_result = {
            "status": "invalid",
            "reason": "O agente juiz não conseguiu validar a resposta.",
            "evidence_ids": [],
            "error_code": "JUDGE_ADAPTER_FAILURE",
        }

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
    *,
    context_enricher: ConversationContextEnricherPort,
) -> GraphUpdate:
    request = state.get("request")
    if not request or not request.get("is_resuming_conversation", False):
        return {}

    user_id = request.get("user_id", "").strip()
    conversation_id = request.get("conversation_id", "").strip()
    if not user_id or not conversation_id:
        raise ValueError("user_id e conversation_id são necessários para retomada")

    current_state = sanitized_state(state)
    current_messages = list(current_state.get("messages", []))
    restored_messages = context_enricher.restore_messages(
        user_id=user_id,
        conversation_id=conversation_id,
    )

    current_ids = [message.id for message in current_messages if message.id]
    current_id_set = set(current_ids)
    historical_messages = [
        message for message in restored_messages if message.id not in current_id_set
    ]
    restored_state_messages: list[Any] = [
        *(RemoveMessage(id=message_id) for message_id in current_ids),
        *historical_messages,
        *current_messages,
    ]
    return {
        "messages": restored_state_messages,
    }


def run_output_guardrail_node(
    state: GraphState,
    *,
    guardrail: GraphNode,
) -> GraphUpdate:
    return guardrail(state)
