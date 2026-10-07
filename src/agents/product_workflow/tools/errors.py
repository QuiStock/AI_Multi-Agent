"""Safe error and metadata responses for Product Workflow tools."""

from __future__ import annotations

from datetime import UTC, datetime

from src.agents.product_workflow.models import ProductWorkflowContext
from src.agents.product_workflow.repository import (
    ProductWorkflowDependencyError,
)
from src.agents.schemas.tool_result import (
    ResponseContent,
    ToolErrorCategory,
    ToolMetadata,
)
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    create_tool_error,
    create_tool_metadata,
    tool_error,
)


def metadata(*, tool_name: str, context: ProductWorkflowContext) -> ToolMetadata:
    return create_tool_metadata(
        tool_name=tool_name,
        tool_version="1.0.0",
        tool_call_id=f"{context.request_id}:{tool_name}",
        trace_id=context.trace_id,
        timestamp=datetime.now(UTC),
    )


def selection_error(*, tool_name: str, context: ProductWorkflowContext) -> str:
    return serialize_for_agent(
        tool_error(
            error=create_tool_error(
                code="INVALID_SELECTION_REF",
                category="validation",
                message="A seleção do produto é inválida ou expirou.",
            ),
            meta=metadata(tool_name=tool_name, context=context),
            content=ResponseContent(
                text="Não foi possível identificar a sugestão selecionada."
            ),
        )
    )


def not_found(*, tool_name: str, context: ProductWorkflowContext) -> str:
    return serialize_for_agent(
        tool_error(
            error=create_tool_error(
                code="SUGGESTION_NOT_FOUND",
                category="not_found",
                message="A sugestão não foi encontrada no escopo autorizado.",
            ),
            meta=metadata(tool_name=tool_name, context=context),
            content=ResponseContent(
                text="A sugestão não foi encontrada no escopo autorizado."
            ),
        )
    )


def failure(
    *,
    tool_name: str,
    context: ProductWorkflowContext,
    error: Exception,
) -> str:
    if isinstance(error, ProductWorkflowDependencyError):
        category: ToolErrorCategory = "dependency"
        code = "PRODUCT_WORKFLOW_UNAVAILABLE"
        message = "A fonte comercial está indisponível no momento."
        retryable = True
    elif isinstance(error, PermissionError):
        category = "authorization"
        code = "PRODUCT_WORKFLOW_FORBIDDEN"
        message = "Cargo sem acesso à consulta do fluxo de produtos."
        retryable = False
    elif isinstance(error, ValueError):
        category = "validation"
        code = "PRODUCT_WORKFLOW_INVALID_INPUT"
        message = "A consulta do fluxo de produtos é inválida."
        retryable = False
    else:
        category = "internal"
        code = "PRODUCT_WORKFLOW_INTERNAL"
        message = "Não foi possível concluir a consulta do fluxo de produtos."
        retryable = False
    return serialize_for_agent(
        tool_error(
            error=create_tool_error(
                code=code,
                category=category,
                message=message,
                retryable=retryable,
            ),
            meta=metadata(tool_name=tool_name, context=context),
            content=ResponseContent(text=message),
        )
    )
