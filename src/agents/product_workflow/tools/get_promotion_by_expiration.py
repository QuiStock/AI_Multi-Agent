"""Find promotions by extreme validity or through a civil until date."""

from __future__ import annotations

from datetime import date
from typing import Literal

from langchain_core.tools import BaseTool, tool

from src.agents.product_workflow.filters import (
    MAX_PRODUCT_SEARCH_PAGE,
    PRODUCT_SEARCH_PAGE_SIZE,
)
from src.agents.product_workflow.repository import ProductWorkflowRepository
from src.agents.tooling.result_factory import ToolResultExtras, compose_success

from ..contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionListingRecord,
    ProductWorkflowContext,
)
from .schemas import (
    OnToolResult,
    PromotionExpirationData,
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

_TOOL_NAME = "get_promotion_by_expiration"


def create_get_promotion_by_expiration_tool(
    *,
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    reference_date: date,
    on_result: OnToolResult | None = None,
) -> BaseTool:
    @tool
    def get_promotion_by_expiration(
        direction: Literal["nearest", "longest"] | None = None,
        until: str | None = None,
        page: int = 1,
    ) -> str:
        """Encontra promoções pela validade extrema ou até uma data.

        direction é nearest ou longest quando o usuário pede a validade mais
        próxima ou mais distante. until, em AAAA-MM-DD, lista promoções cuja
        validade fica entre a data da mensagem e essa data, inclusive. Não
        envie direction quando usar until. page começa em 1 e mostra no máximo
        6 sugestões. Não percorra páginas sozinho: só avance quando o usuário
        pedir a próxima.
        """

        try:
            if type(page) is not int or page < 1 or page > MAX_PRODUCT_SEARCH_PAGE:
                raise ValueError("Página de produtos inválida")
            until_date = _parse_until(until)
            rows = repository.find_promotions_by_expiration(
                context,
                None if until_date is not None else direction,
                reference_date=reference_date,
                until=until_date,
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
                data = PromotionExpirationData(
                    direction=None if until_date is not None else direction,
                    until=until_date,
                    page=page,
                    has_more=False,
                    status="unique",
                    suggestion=suggestion_card(
                        detail,
                        selection_id=create_selection_id(detail),
                    ),
                )
            elif records:
                shared_date = (
                    _shared_valid_until(records) if until_date is None else None
                )
                data = PromotionExpirationData(
                    direction=None if until_date is not None else direction,
                    until=until_date,
                    page=page,
                    has_more=has_more,
                    status="ambiguous",
                    promotion_valid_until=shared_date,
                    candidates=[
                        candidate_data(record, page_position(page, index))
                        for index, record in enumerate(records)
                    ],
                )
            else:
                data = PromotionExpirationData(
                    direction=None if until_date is not None else direction,
                    until=until_date,
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
                            evidence_key("promotion-expiration", payload),
                            payload,
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

    return get_promotion_by_expiration


def _parse_until(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("Data until inválida") from exc


def _shared_valid_until(
    records: list[ProductSuggestionListingRecord],
) -> date | None:
    if not records:
        return None
    first = records[0].promotion_valid_until
    if first is None:
        return None
    if any(record.promotion_valid_until != first for record in records):
        return None
    return first


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
