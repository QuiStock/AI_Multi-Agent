from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.schemas.conversation import ConversationResponse
from src.api.services.conversation_end_service import (
    ConversationAlreadyEndedError,
    SummaryQueueUnavailableError,
)
from src.api.services.conversation_list_service import ConversationListValidationError
from src.memory.mongo_repository import (
    ConversationClosedError,
    ConversationNotEndedError,
    ConversationNotFoundError,
)


class GraphExecutionError(RuntimeError):
    """Raised when the graph cannot produce a valid endpoint response."""


@dataclass(frozen=True, slots=True)
class InputRejectedError(Exception):
    """Carries a controlled input-guardrail response to the HTTP handler."""

    response: ConversationResponse


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


async def handle_conversation_not_found(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    cast(ConversationNotFoundError, exc)
    return _error_response(
        status_code=404,
        code="CONVERSATION_NOT_FOUND",
        message="A conversa não foi encontrada.",
    )


async def handle_conversation_conflict(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    conflict = cast(ConversationClosedError | ConversationNotEndedError, exc)
    message = (
        "A conversa está encerrada e precisa ser retomada antes de receber mensagens."
        if isinstance(conflict, ConversationClosedError)
        else "A conversa selecionada não está encerrada para retomada."
    )
    return _error_response(
        status_code=409,
        code="CONVERSATION_STATE_CONFLICT",
        message=message,
    )


async def handle_input_rejected(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    rejected = cast(InputRejectedError, exc)
    return JSONResponse(
        status_code=422,
        content=rejected.response.model_dump(mode="json"),
    )


async def handle_graph_execution_error(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    cast(GraphExecutionError, exc)
    return _error_response(
        status_code=500,
        code="GRAPH_EXECUTION_FAILED",
        message="Não foi possível processar a mensagem.",
    )


async def handle_conversation_already_ended(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    cast(ConversationAlreadyEndedError, exc)
    return _error_response(
        status_code=409,
        code="CONVERSATION_ALREADY_ENDED",
        message="A conversa já foi encerrada.",
    )


async def handle_summary_queue_unavailable(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    cast(SummaryQueueUnavailableError, exc)
    return _error_response(
        status_code=503,
        code="SUMMARY_QUEUE_UNAVAILABLE",
        message=(
            "A conversa foi encerrada, mas o processamento do resumo "
            "aguarda nova tentativa."
        ),
    )


async def handle_conversation_list_validation(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    cast(ConversationListValidationError, exc)
    return _error_response(
        status_code=422,
        code="INVALID_CONVERSATION_LIST_REQUEST",
        message="user_id é obrigatório.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        ConversationNotFoundError,
        handle_conversation_not_found,
    )
    app.add_exception_handler(
        ConversationClosedError,
        handle_conversation_conflict,
    )
    app.add_exception_handler(
        ConversationNotEndedError,
        handle_conversation_conflict,
    )
    app.add_exception_handler(InputRejectedError, handle_input_rejected)
    app.add_exception_handler(GraphExecutionError, handle_graph_execution_error)
    app.add_exception_handler(
        ConversationAlreadyEndedError,
        handle_conversation_already_ended,
    )
    app.add_exception_handler(
        SummaryQueueUnavailableError,
        handle_summary_queue_unavailable,
    )
    app.add_exception_handler(
        ConversationListValidationError,
        handle_conversation_list_validation,
    )
