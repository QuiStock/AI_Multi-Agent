"""Revalidate one numbered selection and return its card."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from src.agents.product_workflow.filters import MANAGER_ROLE_CODE
from src.agents.product_workflow.repository import ProductWorkflowRepository
from src.agents.tooling.result_factory import ToolResultExtras, compose_success

from ..contracts import ProductSuggestionDetailRecord, ProductWorkflowContext
from .schemas import (
    OnToolResult,
    SuggestionDetailData,
    domain_error_result,
    emit_result,
    evidence_key,
    failure_result,
    legacy_selection_fingerprint,
    parse_selection_token,
    public_dict,
    selection_fingerprint,
    suggestion_card,
    tool_metadata,
    workflow_evidence,
)

_TOOL_NAME = "get_suggestion_detail"


def create_get_suggestion_detail_tool(
    *,
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    on_result: OnToolResult | None = None,
) -> BaseTool:
    @tool
    def get_suggestion_detail(selection_id: str) -> str:
        """Retorna o card da sugestão escolhida depois de revalidar o escopo.

        Chame somente depois que o usuário escolher um número da página atual.
        Se a busca já veio com status unique, o card já está na resposta.
        """

        try:
            suggestion_id, fingerprint = parse_selection_token(selection_id)
            detail = repository.get_product_suggestion_detail(context, suggestion_id)
            if detail is None or not _fingerprint_matches(detail, fingerprint):
                return emit_result(
                    domain_error_result(
                        tool_name=_TOOL_NAME,
                        context=context,
                        code="SUGGESTION_NOT_FOUND",
                        category="not_found",
                        message="A sugestão não foi encontrada no escopo autorizado.",
                    ),
                    on_result,
                )
            data = SuggestionDetailData(
                visibility=(
                    "manager" if context.role_code == MANAGER_ROLE_CODE else "employee"
                ),
                card=suggestion_card(detail, selection_id=selection_id),
            )
            payload = public_dict(data)
            result = compose_success(
                data=payload,
                meta=tool_metadata(_TOOL_NAME, context),
                extras=ToolResultExtras(
                    evidence=(
                        workflow_evidence(
                            evidence_key("suggestion-detail", payload),
                            payload,
                        ),
                    )
                ),
            )
        except ValueError:
            return emit_result(
                domain_error_result(
                    tool_name=_TOOL_NAME,
                    context=context,
                    code="INVALID_SELECTION_REF",
                    category="validation",
                    message="A seleção do produto é inválida ou expirou.",
                ),
                on_result,
            )
        except Exception as exc:
            return emit_result(
                failure_result(tool_name=_TOOL_NAME, context=context, error=exc),
                on_result,
            )
        return emit_result(result, on_result)

    return get_suggestion_detail


def _fingerprint_matches(detail: object, fingerprint: str | None) -> bool:
    if fingerprint is None:
        return True
    if not isinstance(detail, ProductSuggestionDetailRecord):
        return False
    return fingerprint in {
        selection_fingerprint(detail),
        legacy_selection_fingerprint(detail),
    }
