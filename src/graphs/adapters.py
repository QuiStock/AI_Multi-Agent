from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
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
    ProductWorkFlowResult,
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
        email: str,
        conversation_id: str,
    ) -> list[AnyMessage]: ...


class MemoryMessagePersistencePort(Protocol):
    """Persist the user and assistant messages of one accepted turn."""

    def save_turn(  # noqa: PLR0913 - one persistence operation needs both messages
        self,
        *,
        conversation_id: str,
        email: str,
        request_id: str,
        sanitized_user_content: str,
        assistant_content: str,
        consulted_agents: list[str],
        sent_at: datetime | None = None,
    ) -> None: ...


class FAQExecutorPort(Protocol):
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


class ProductWorkflowExecutorPort(Protocol):
    def invoke(self, state: GraphState) -> dict[str, Any]: ...


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
    """Keep private PII restoration data away from agent executors."""
    agent_state = dict(state)
    agent_state.pop("pii_map", None)
    return cast(GraphState, agent_state)


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
            "request": current_state.get("request"),
        }
    )

    answer = str(result.get("answer", "")).strip()
    evidences = cast(
        list[Evidence],
        result.get("evidences", []),
    )

    citation_ids = [evidence["evidence_id"] for evidence in evidences]

    faq_result: FAQResult = {
        "status": "success" if answer and evidences else "unavailable",
        "answer": answer,
        "citation_ids": citation_ids,
    }
    error_code = result.get("error_code")
    if isinstance(error_code, str) and error_code:
        faq_result["error_code"] = error_code

    return {
        "agent_results": {
            "faq": faq_result,
        },
        "evidences": evidences,
    }


def run_product_workflow_node(
    state: GraphState,
    *,
    executor: ProductWorkflowExecutorPort,
) -> GraphUpdate:
    current_state = sanitized_state(state)
    result = executor.invoke(current_state)
    answer = str(result.get("answer", "")).strip()
    evidences = cast(list[Evidence], result.get("evidences", []))
    error_code = result.get("error_code")
    product_result: ProductWorkFlowResult = {
        "status": "success"
        if answer and evidences
        else "unavailable"
        if error_code == "PRODUCT_WORKFLOW_UNAVAILABLE"
        else "error",
        "answer": answer,
        "evidence_ids": [item["evidence_id"] for item in evidences],
    }
    if isinstance(error_code, str) and error_code:
        product_result["error_code"] = error_code
    return {
        "agent_results": {
            "product_workflow": product_result,
        },
        "evidences": evidences,
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
    result = compiler.invoke(sanitized_state(state))

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

    email = request.get("email", "").strip()
    conversation_id = request.get("conversation_id", "").strip()
    if not email or not conversation_id:
        raise ValueError("email e conversation_id são necessários para retomada")

    request_id = request.get("request_id", "").strip()
    if not request_id:
        raise ValueError("request_id é necessário para retomada")

    current_messages = list(state.get("messages", []))
    restored_messages = context_enricher.restore_messages(
        email=email,
        conversation_id=conversation_id,
    )

    current_human = next(
        (
            message
            for message in reversed(current_messages)
            if isinstance(message, HumanMessage) and message.id == f"{request_id}:user"
        ),
        None,
    )
    if current_human is None:
        raise ValueError("A mensagem atual do usuário é necessária para retomada")
    if not isinstance(current_human.content, str) or not current_human.content.strip():
        raise ValueError("A mensagem sanitizada do usuário é inválida")

    current_message = HumanMessage(
        content=current_human.content,
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
        request.get("email", "").strip(),
        request.get("request_id", "").strip(),
    )
    if not all(values):
        raise ValueError(
            "conversation_id, email e request_id são necessários "
            "para persistir mensagens"
        )
    return values


def run_normalize_user_message_node(state: GraphState) -> GraphUpdate:
    """Ensure the current sanitized user message has this request's stable ID."""
    _, _, request_id = _request_for_persistence(state)
    message_id = f"{request_id}:user"
    messages = list(state.get("messages", []))
    current_human = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
        ),
        None,
    )
    if current_human is None:
        raise ValueError("A mensagem sanitizada do usuário não foi encontrada")
    if not isinstance(current_human.content, str) or not current_human.content.strip():
        raise ValueError("A mensagem sanitizada do usuário é inválida")
    if current_human.id == message_id:
        return {}
    updates: list[AnyMessage] = []
    if current_human.id:
        updates.append(cast(AnyMessage, RemoveMessage(id=current_human.id)))
    updates.append(HumanMessage(content=current_human.content, id=message_id))
    return {"messages": updates}


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
    conversation_id, email, request_id = _request_for_persistence(state)
    user_message_id = f"{request_id}:user"
    user_message = next(
        (
            message
            for message in reversed(state.get("messages", []))
            if isinstance(message, HumanMessage) and message.id == user_message_id
        ),
        None,
    )
    if user_message is None:
        raise ValueError("A mensagem sanitizada do turno não foi encontrada")
    if not isinstance(user_message.content, str) or not user_message.content.strip():
        raise ValueError("A mensagem sanitizada do turno é inválida")

    target_agent = state.get("routing_decision", {}).get("target_agent")
    consulted_agents = [target_agent] if isinstance(target_agent, str) else []
    sent_at = request.get("sent_at") if request else None
    if sent_at is not None and not isinstance(sent_at, datetime):
        raise ValueError("sent_at precisa ser um datetime com timezone")

    if message_service is not None:
        message_service.save_turn(
            conversation_id=conversation_id,
            email=email,
            request_id=request_id,
            sanitized_user_content=user_message.content,
            assistant_content=content,
            consulted_agents=consulted_agents,
            sent_at=sent_at,
        )

    return {
        "messages": [
            AIMessage(
                content=content,
                id=f"{request_id}:assistant",
            )
        ],
        "pii_map": {},
        "status": "completed",
    }


def run_output_guardrail_node(
    state: GraphState,
    *,
    guardrail: GraphNode,
) -> GraphUpdate:
    return guardrail(state)
