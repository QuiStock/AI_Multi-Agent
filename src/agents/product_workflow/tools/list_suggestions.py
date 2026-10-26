"""List authorized ORDER or PROMOTION suggestions, six at a time."""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool, tool

from src.agents.product_workflow.filters import (
    MAX_PRODUCT_SEARCH_PAGE,
    PRODUCT_SEARCH_PAGE_SIZE,
)
from src.agents.product_workflow.repository import (
    ProductWorkflowRepository,
    normalize_suggestion_types,
)
from src.agents.tooling.result_factory import ToolResultExtras, compose_success

from ..contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionListingRecord,
    ProductWorkflowContext,
)
from .schemas import (
    OnToolResult,
    SuggestionListData,
    candidate_data,
    create_selection_id,
    emit_result,
    evidence_key,
    failure_result,
    page_position,
    public_dict,
    selection_fingerprint,
    suggestion_card,
    tool_metadata,
    workflow_evidence,
)

_TOOL_NAME = "list_suggestions"


def create_list_suggestions_tool(
    *,
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    on_result: OnToolResult | None = None,
) -> BaseTool:
    @tool
    def list_suggestions(
        suggestion_type: Literal["ORDER", "PROMOTION"]
        | list[Literal["ORDER", "PROMOTION"]],
        page: int = 1,
    ) -> str:
        """Lista seis sugestões ORDER, PROMOTION ou as duas.

        Passe ["ORDER", "PROMOTION"] quando o usuário não especificar o tipo.
        page começa em 1 e mostra no máximo 6 sugestões. Não percorra páginas
        sozinho: só avance quando o usuário pedir a próxima.
        """

        try:
            if type(page) is not int or page < 1 or page > MAX_PRODUCT_SEARCH_PAGE:
                raise ValueError("Página de produtos inválida")
            suggestion_types = normalize_suggestion_types(suggestion_type)
            rows = repository.list_product_suggestions(
                context,
                suggestion_types,
                page=page,
            )
            has_more = len(rows) > PRODUCT_SEARCH_PAGE_SIZE
            records = rows[:PRODUCT_SEARCH_PAGE_SIZE]
            detail = (
                _matching_detail(repository, context, records[0])
                if page == 1 and len(records) == 1 and not has_more
                else None
            )
            if detail is not None:
                data = SuggestionListData(
                    suggestion_types=suggestion_types,
                    page=page,
                    has_more=False,
                    status="unique",
                    suggestion=suggestion_card(
                        detail,
                        selection_id=create_selection_id(detail),
                    ),
                )
            elif records:
                data = SuggestionListData(
                    suggestion_types=suggestion_types,
                    page=page,
                    has_more=has_more,
                    status="ambiguous",
                    candidates=[
                        candidate_data(record, page_position(page, index))
                        for index, record in enumerate(records)
                    ],
                )
            else:
                data = SuggestionListData(
                    suggestion_types=suggestion_types,
                    page=page,
                    has_more=False,
                    status="not_found",
                )
            payload = public_dict(data)
            result = compose_success(
                data=payload,
                meta=tool_metadata(_TOOL_NAME, context),
                extras=ToolResultExtras(
                    evidence=(
                        workflow_evidence(
                            evidence_key("suggestion-list", payload), payload
                        ),
                    )
                ),
            )
        except Exception as exc:
            return emit_result(
                failure_result(tool_name=_TOOL_NAME, context=context, error=exc),
                on_result,
            )
        return emit_result(result, on_result)

    return list_suggestions


def _matching_detail(
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    record: ProductSuggestionListingRecord,
) -> ProductSuggestionDetailRecord | None:
    detail = repository.get_product_suggestion_detail(context, record.suggestion_id)
    if isinstance(detail, ProductSuggestionDetailRecord) and selection_fingerprint(
        detail
    ) == selection_fingerprint(record):
        return detail
    return None
