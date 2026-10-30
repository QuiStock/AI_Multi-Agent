from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal, Protocol
from uuid import uuid4

from langchain_core.messages import HumanMessage

from src.api.errors import GraphExecutionError, InputRejectedError
from src.api.schemas.conversation import ConversationRequest, ConversationResponse
from src.config import settings
from src.graphs.state import GraphState, RequestContext
from src.guardrails.config import GuardrailConfig
from src.guardrails.pii import redact_sensitive_data, restore_pii_placeholders
from src.memory.mongo_repository import (
    ConversationClosedError,
    ConversationNotEndedError,
    ConversationNotFoundError,
)
from src.observability.live_trace_store import live_trace_store
from src.observability.log_capture import CorrelatedLogCapture
from src.observability.traces import TraceRecorder

logger = logging.getLogger(__name__)


class ConversationGraph(Protocol):
    def invoke(
        self,
        input: Any,
        config: Any = None,
    ) -> Any: ...


class TraceRepository(Protocol):
    def save_trace(self, trace: Mapping[str, Any]) -> None: ...


class ConversationService:
    """Translate an HTTP conversation request into one graph invocation."""

    def __init__(
        self,
        graph: ConversationGraph,
        trace_repository: TraceRepository | None = None,
    ) -> None:
        self._graph = graph
        self._trace_repository = trace_repository
        self._guardrail_config = GuardrailConfig()

    def converse(  # noqa: C901, PLR0912, PLR0913, PLR0915
        self,
        *,
        conversation_id: str,
        request: ConversationRequest,
        email: str,
        role_code: str | None = None,
        user_id: int | None = None,
        store_ids: tuple[int, ...] = (),
        role_id: int | None = None,
        request_id: str | None = None,
    ) -> ConversationResponse:
        normalized_conversation_id = conversation_id.strip()
        if not normalized_conversation_id:
            raise ValueError("conversation_id é obrigatório")

        effective_request_id = request_id or str(uuid4())
        trace_id = effective_request_id
        effective_role_code = role_code or ""
        if not effective_role_code:
            raise ValueError("role_code e obrigat\u00f3rio")
        pii_redaction_enabled = (
            self._guardrail_config.enabled
            and self._guardrail_config.redact_sensitive_data
        )
        request_pii_map: dict[str, str] = {}
        if pii_redaction_enabled:
            sanitized_message, _, request_pii_map = redact_sensitive_data(
                request.message,
                namespace=effective_request_id,
            )
        else:
            sanitized_message = request.message
        request_context: RequestContext = {
            "request_id": effective_request_id,
            "trace_id": trace_id,
            "email": email,
            "role_code": effective_role_code,
            "conversation_id": normalized_conversation_id,
            "sent_at": request.sent_at,
            "is_new_conversation": not request.is_resuming_conversation,
            "is_resuming_conversation": request.is_resuming_conversation,
            "pii_redacted_before_graph": pii_redaction_enabled,
            "original_message_length": len(request.message),
            "product_card": request.product_card.model_dump(mode="json")
            if request.product_card
            else None,
        }
        if user_id is not None:
            request_context["user_id"] = user_id
        if store_ids:
            request_context["store_ids"] = list(store_ids)
        if role_id is not None:
            request_context["role_id"] = role_id
        state: GraphState = {
            "request": request_context,
            "messages": [
                HumanMessage(
                    content=sanitized_message,
                    id=f"{effective_request_id}:user",
                )
            ],
        }

        live_trace_store.start_trace(
            trace_id=trace_id,
            conversation_id=normalized_conversation_id,
            environment=settings.app_environment,
        )
        trace_recorder = TraceRecorder(
            trace_id=trace_id,
            conversation_id=normalized_conversation_id,
            environment=settings.app_environment,
            event_publisher=live_trace_store.publish,
        )
        log_capture = CorrelatedLogCapture(
            trace_id=trace_id,
            conversation_id=normalized_conversation_id,
            event_publisher=live_trace_store.publish_log,
        )
        trace_status: Literal["completed", "error"] = "error"

        try:
            with log_capture.capture():
                logger.info(
                    "conversation_turn_started",
                    extra={
                        "event": "conversation_turn_started",
                        "environment": settings.app_environment,
                    },
                )
                try:
                    result = self._graph.invoke(
                        state,
                        config={
                            "configurable": {
                                "thread_id": normalized_conversation_id,
                            },
                            "metadata": {
                                "trace_id": trace_id,
                                "conversation_id": normalized_conversation_id,
                                "environment": settings.app_environment,
                            },
                            "callbacks": [trace_recorder],
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
                            "request_id": effective_request_id,
                            "trace_id": trace_id,
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
                response_content = restore_pii_placeholders(content, request_pii_map)
                if status not in {
                    "success",
                    "rejected",
                    "clarification_required",
                    "out_of_scope",
                    "error",
                }:
                    raise GraphExecutionError("final_response.status inválido")

                trace_status = "error" if status == "error" else "completed"
                logger.info(
                    "conversation_turn_completed",
                    extra={
                        "event": "conversation_turn_completed",
                        "status": status,
                    },
                )
                response = ConversationResponse(
                    conversation_id=normalized_conversation_id,
                    request_id=effective_request_id,
                    response=response_content,
                    status=status,
                )

                if status == "rejected":
                    raise InputRejectedError(response)

                return response
        finally:
            try:
                trace_recorder.finish_trace(status=trace_status)
            except Exception:
                logger.exception(
                    "observability_trace_finalize_failed",
                    extra={
                        "conversation_id": normalized_conversation_id,
                        "trace_id": trace_id,
                    },
                )
            else:
                if self._trace_repository is not None:
                    try:
                        trace_document = trace_recorder.to_document()
                        trace_document["logs"] = list(log_capture.records)
                        self._trace_repository.save_trace(trace_document)
                    except Exception:
                        logger.exception(
                            "observability_trace_persistence_failed",
                            extra={
                                "conversation_id": normalized_conversation_id,
                                "trace_id": trace_id,
                            },
                        )
            trace_document = trace_recorder.to_document()
            live_trace_store.finish_trace(
                trace_id=trace_id,
                conversation_id=normalized_conversation_id,
                status=trace_status,
                duration_ms=trace_document.get("duration_ms"),
            )
