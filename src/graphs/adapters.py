from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, cast

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


class MemoryMessagePersistencePort(Protocol):
    """Persist the user and assistant messages of one accepted turn."""

    def save_user_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        request_id: str,
        sanitized_content: str,
    ) -> bool: ...

    def save_assistant_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        request_id: str,
        content: str,
        consulted_agents: list[str],
    ) -> bool: ...

    def save_turn(
        self,
        *,
        conversation_id: str,
        user_id: str,
        request_id: str,
        sanitized_user_content: str,
        assistant_content: str,
        consulted_agents: list[str],
    ) -> None: ...


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

    sanitized_message = request.get("sanitized_message")
    if not isinstance(sanitized_message, str) or not sanitized_message.strip():
        raise ValueError("sanitized_message é necessário para retomada")

    request_id = request.get("request_id", "").strip()
    if not request_id:
        raise ValueError("request_id é necessário para retomada")

    current_messages = list(state.get("messages", []))
    restored_messages = context_enricher.restore_messages(
        user_id=user_id,
        conversation_id=conversation_id,
    )

    current_human = next(
        (
            message
            for message in reversed(current_messages)
            if isinstance(message, HumanMessage)
        ),
    )
    if current_human is None:
        raise ValueError("A mensagem atual do usuário é necessária para retomada")

    current_message = HumanMessage(
        content=sanitized_message,
        id=f"{request_id}:user",
    )
    current_ids = [message.id for message in current_messages if message.id]
    if not current_ids and current_human.id is None:
        current_ids.append(f"{request_id}:user")
    historical_messages = [
        message for message in restored_messages if message.id != current_message.id
    ]
    restored_state_messages: list[Any] = [
        *(RemoveMessage(id=message_id) for message_id in current_ids),
        *historical_messages,
        current_message,
    ]
    return {
        "messages": restored_state_messages,
    }


def _request_for_persistence(state: GraphState) -> tuple[str, str, str]:
    request = state.get("request")
    if not request:
        raise ValueError("request é necessário para persistir mensagens")

    values = (
        request.get("conversation_id", "").strip(),
        request.get("user_id", "").strip(),
        request.get("request_id", "").strip(),
    )
    if not all(values):
        raise ValueError(
            "conversation_id, user_id e request_id são necessários "
            "para persistir mensagens"
        )
    return values


def run_persist_user_message_node(
    state: GraphState,
    *,
    message_service: MemoryMessagePersistencePort | None,
) -> GraphUpdate:
    """Persist and normalize the accepted user message for this turn."""
    if message_service is None and "request" not in state:
        return {}

    request = state.get("request")
    sanitized_message = request.get("sanitized_message") if request else None
    if not isinstance(sanitized_message, str) or not sanitized_message.strip():
        raise ValueError("sanitized_message é necessário para persistir mensagem")

    conversation_id, user_id, request_id = _request_for_persistence(state)
    message_id = f"{request_id}:user"
    current_messages = list(state.get("messages", []))
    latest_human = next(
        (
            message
            for message in reversed(current_messages)
            if isinstance(message, HumanMessage)
        ),
    )
    updates: list[AnyMessage] = []
    if latest_human is not None and latest_human.id and latest_human.id != message_id:
        updates.append(cast(AnyMessage, RemoveMessage(id=latest_human.id)))
    updates.append(HumanMessage(content=sanitized_message, id=message_id))

    if message_service is not None:
        message_service.save_user_message(
            conversation_id=conversation_id,
            user_id=user_id,
            request_id=request_id,
            sanitized_content=sanitized_message,
        )

    return {"messages": updates}


def run_normalize_user_message_node(state: GraphState) -> GraphUpdate:
    """Normalize the current user message without persisting the turn."""
    return run_persist_user_message_node(state, message_service=None)


def run_persist_turn_node(
    state: GraphState,
    *,
    message_service: MemoryMessagePersistencePort | None,
) -> GraphUpdate:
    """Persist the sanitized user message and final assistant response once."""
    if message_service is None and "request" not in state:
        return {}

    final_response = state.get("final_response")
    if not final_response:
        raise ValueError("final_response é necessário para persistir o turno")

    content = final_response["content"].strip()
    if not content:
        raise ValueError("final_response.content não pode estar vazio")

    request = state.get("request")
    sanitized_message = request.get("sanitized_message") if request else None
    if not isinstance(sanitized_message, str) or not sanitized_message.strip():
        raise ValueError("sanitized_message é necessário para persistir o turno")

    conversation_id, user_id, request_id = _request_for_persistence(state)
    target_agent = state.get("routing_decision", {}).get("target_agent")
    consulted_agents = [target_agent] if isinstance(target_agent, str) else []

    if message_service is not None:
        save_turn = getattr(message_service, "save_turn", None)
        if callable(save_turn):
            save_turn(
                conversation_id=conversation_id,
                user_id=user_id,
                request_id=request_id,
                sanitized_user_content=sanitized_message,
                assistant_content=content,
                consulted_agents=consulted_agents,
            )
        else:
            message_service.save_user_message(
                conversation_id=conversation_id,
                user_id=user_id,
                request_id=request_id,
                sanitized_content=sanitized_message,
            )
            message_service.save_assistant_message(
                conversation_id=conversation_id,
                user_id=user_id,
                request_id=request_id,
                content=content,
                consulted_agents=consulted_agents,
            )

    return {
        "messages": [
            AIMessage(
                content=content,
                id=f"{request_id}:assistant",
            )
        ],
        "pii_map": {},
    }


def run_persist_assistant_message_node(
    state: GraphState,
    *,
    message_service: MemoryMessagePersistencePort | None,
) -> GraphUpdate:
    """Persist the controlled final response of an accepted turn."""
    if message_service is None and "request" not in state:
        return {}

    final_response = state.get("final_response")
    if not final_response:
        raise ValueError("final_response é necessário para persistir resposta")

    content = final_response["content"].strip()
    if not content:
        raise ValueError("final_response.content não pode estar vazio")

    conversation_id, user_id, request_id = _request_for_persistence(state)
    target_agent = state.get("routing_decision", {}).get("target_agent")
    consulted_agents = [target_agent] if isinstance(target_agent, str) else []

    if message_service is not None:
        message_service.save_assistant_message(
            conversation_id=conversation_id,
            user_id=user_id,
            request_id=request_id,
            content=content,
            consulted_agents=consulted_agents,
        )

    return {
        "messages": [
            AIMessage(
                content=content,
                id=f"{request_id}:assistant",
            )
        ]
    }


def run_output_guardrail_node(
    state: GraphState,
    *,
    guardrail: GraphNode,
) -> GraphUpdate:
    return guardrail(state)
