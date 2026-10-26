from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
)

from src.graphs.state import GraphState

GraphUpdate = GraphState
GraphNode = Callable[[GraphState], GraphUpdate]
logger = logging.getLogger(__name__)


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
    logger.info(
        "conversation_context_restored",
        extra={
            "event": "conversation_context_restored",
            "message_count": len(restored_messages),
        },
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

    current_message_id = f"{request_id}:user"
    current_message = HumanMessage(
        content=current_human.content,
        id=current_message_id,
    )
    historical_messages = [
        message for message in restored_messages if message.id != current_message_id
    ]
    restored_state_messages: list[Any] = [
        RemoveMessage(id=current_message_id),
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

    routing_decision = state.get("routing_decision", {})
    route = routing_decision.get("route")
    consulted_agents = (
        [route]
        if routing_decision.get("outcome") == "dispatch"
        and route in {"faq", "product_workflow"}
        else []
    )
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
        logger.info(
            "conversation_turn_persisted",
            extra={
                "event": "conversation_turn_persisted",
                "message_count": 2,
            },
        )

    return {
        "messages": [
            AIMessage(
                content=content,
                id=f"{request_id}:assistant",
            )
        ],
        "status": "completed",
    }


