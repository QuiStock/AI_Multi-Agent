"""Search authorized suggestions by partial name or SKU."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from src.agents.product_workflow.filters import (
    MAX_PRODUCT_SEARCH_PAGE,
    PRODUCT_SEARCH_PAGE_SIZE,
)
from src.agents.product_workflow.repository import ProductWorkflowRepository
from src.agents.tooling.result_factory import ToolResultExtras, compose_success

from ..contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)
from .schemas import (
    OnToolResult,
    ProductSearchData,
    SuggestionCandidateData,
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

_TOOL_NAME = "get_suggestion_for_product"


def create_get_suggestion_for_product_tool(
    *,
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    on_result: OnToolResult | None = None,
) -> BaseTool:
    @tool
    def get_suggestion_for_product(product_query: str, page: int = 1) -> str:
        """Busca sugestões autorizadas por nome parcial ou SKU.

        page começa em 1 e mostra no máximo 6 sugestões. Não percorra páginas
        sozinho: só avance quando o usuário pedir a próxima.
        """

        try:
            if type(page) is not int or page < 1 or page > MAX_PRODUCT_SEARCH_PAGE:
                raise ValueError("Página de produtos inválida")
            rows = repository.search_product_suggestions(
                context,
                product_query,
                page=page,
            )
            has_more = len(rows) > PRODUCT_SEARCH_PAGE_SIZE
            page_rows = rows[:PRODUCT_SEARCH_PAGE_SIZE]
            if not page_rows:
                data = ProductSearchData(
                    product_query=product_query.strip(),
                    page=page,
                    has_more=False,
                    status="not_found",
                )
            elif page == 1 and len(page_rows) == 1 and not has_more:
                data = _unique_search(repository, context, product_query, page_rows[0])
            else:
                data = ProductSearchData(
                    product_query=product_query.strip(),
                    page=page,
                    has_more=has_more,
                    status="ambiguous",
                    candidates=[
                        _candidate(record, page_position(page, index))
                        for index, record in enumerate(page_rows)
                    ],
                )
            payload = public_dict(data)
            result = compose_success(
                data=payload,
                meta=tool_metadata(_TOOL_NAME, context),
                extras=ToolResultExtras(
                    evidence=(
                        workflow_evidence(
                            evidence_key("product-search", payload), payload
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

    return get_suggestion_for_product


def _candidate(
    record: ProductSuggestionSearchRecord,
    position: int,
) -> SuggestionCandidateData:
    return SuggestionCandidateData(
        position=position,
        selection_id=create_selection_id(record),
        product_name=record.product_name,
        category_name=record.category_name,
        sku=record.sku,
        suggestion_type=record.suggestion_type,
    )


def _unique_search(
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    product_query: str,
    record: ProductSuggestionSearchRecord,
) -> ProductSearchData:
    detail = repository.get_product_suggestion_detail(context, record.suggestion_id)
    if not _same_candidate(record, detail):
        return ProductSearchData(
            product_query=product_query.strip(),
            page=1,
            has_more=False,
            status="not_found",
        )
    assert detail is not None
    return ProductSearchData(
        product_query=product_query.strip(),
        page=1,
        has_more=False,
        status="unique",
        suggestion=suggestion_card(detail, selection_id=create_selection_id(detail)),
    )


def _same_candidate(
    record: ProductSuggestionSearchRecord,
    detail: ProductSuggestionDetailRecord | None,
) -> bool:
    return detail is not None and selection_fingerprint(
        detail
    ) == selection_fingerprint(record)
