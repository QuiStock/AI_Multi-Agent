from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import uuid4

from langchain_core.messages import HumanMessage

from src.api.errors import GraphExecutionError, InputRejectedError
from src.api.schemas.conversation import ConversationRequest, ConversationResponse
from src.graphs.state import GraphState, RequestContext
from src.memory.mongo_repository import (
    ConversationClosedError,
    ConversationNotEndedError,
    ConversationNotFoundError,
)

logger = logging.getLogger(__name__)


class ConversationGraph(Protocol):
    def invoke(
        self,
        input: Any,
        config: Any = None,
    ) -> Any: ...


class ConversationService:
    """Translate an HTTP conversation request into one graph invocation."""

    def __init__(self, graph: ConversationGraph) -> None:
        self._graph = graph

    def converse(
        self,
        *,
        conversation_id: str,
        request: ConversationRequest,
        email: str,
        role_id: int | None = None,
    ) -> ConversationResponse:
        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise ValueError("conversation_id é obrigatório")

        request_id = str(uuid4())
        request_context: RequestContext = {
            "request_id": request_id,
            "email": email,
            "conversation_id": normalized_conversation_id,
            "sent_at": request.sent_at,
            "is_new_conversation": not request.is_resuming_conversation,
            "is_resuming_conversation": request.is_resuming_conversation,
        }
        if role_id is not None:
            request_context["role_id"] = role_id
        state: GraphState = {
            "request": request_context,
            "messages": [
                HumanMessage(
                    content=request.message,
                    id=f"{request_id}:user",
                )
            ],
        }

        try:
            result = self._graph.invoke(
                state,
                config={
                    "configurable": {
                        "thread_id": normalized_conversation_id,
                    }
                },
            )
        except (
            ConversationClosedError,
            ConversationNotEndedError,
            ConversationNotFoundError,
        ):
            raise
        except Exception as exc:
            logger.exception(
                "conversation_graph_failed",
                extra={
                    "conversation_id": normalized_conversation_id,
                    "request_id": request_id,
                },
            )
            raise GraphExecutionError from exc

        final_response = result.get("final_response")
        if not isinstance(final_response, Mapping):
            raise GraphExecutionError("O grafo não retornou final_response")

        content = final_response.get("content")
        status = final_response.get("status")
        if not isinstance(content, str) or not content.strip():
            raise GraphExecutionError("final_response.content inválido")
        if status not in {
            "success",
            "rejected",
            "clarification_required",
            "out_of_scope",
            "error",
        }:
            raise GraphExecutionError("final_response.status inválido")

        response = ConversationResponse(
            conversation_id=normalized_conversation_id,
            request_id=request_id,
            response=content,
            status=status,
        )

        if status == "rejected":
            raise InputRejectedError(response)

        return response
