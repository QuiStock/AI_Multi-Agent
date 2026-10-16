from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool, tool

from src.agents.product_workflow.filters import (
    DEFAULT_SUGGESTION_PAGE_SIZE,
    MANAGER_ROLE_CODE,
    MAX_PROMOTION_TIE_PAGE_SIZE,
)
from src.agents.product_workflow.models import (
    ProductSuggestionCandidate,
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchData,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
    PromotionExpirationData,
    SuggestionDetailData,
    SuggestionListData,
)
from src.agents.product_workflow.repository import ProductWorkflowRepository
from src.agents.schemas.tool_result import (
    DirectResponse,
    ResponseContent,
    ToolEvidence,
    ToolWarning,
)
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_compose_response,
    direct_success,
    partial_result,
)

from .errors import failure, metadata, not_found, selection_error
from .evidence import (
    candidate_evidence,
    detail_evidence,
    no_more_promotions_page_evidence,
    no_more_suggestions_page_evidence,
    no_suggestions_for_type_evidence,
    no_valid_promotion_evidence,
    triage_evidence,
)
from .projections import build_detail_data
from .selection import (
    create_selection_id,
    create_selection_ref,
    parse_selection_token,
    selection_fingerprint,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductWorkflowToolContext:
    repository: ProductWorkflowRepository
    authorized: ProductWorkflowContext


def build_product_workflow_tools(
    *,
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
) -> list[BaseTool]:
    tool_context = ProductWorkflowToolContext(
        repository=repository,
        authorized=context,
    )

    @tool
    def get_suggestion_for_product(product_query: str) -> str:
        """Localiza uma sugestão autorizada por nome, SKU ou identificador."""

        try:
            records = tool_context.repository.search_product_suggestions(
                tool_context.authorized,
                product_query,
                limit=6,
            )
            candidates = [
                ProductSuggestionCandidate(
                    position=index,
                    selection_id=create_selection_id(record),
                    selection_ref=create_selection_ref(record),
                    suggestion_id=record.suggestion_id,
                    product_id=record.product_id,
                    product_name=record.product_name,
                    category_name=record.category_name,
                    sku=record.sku,
                    store_name=record.store_name,
                    suggestion_type=record.suggestion_type,
                    suggestion_status=record.suggestion_status,
                )
                for index, record in enumerate(records, start=1)
            ]
            normalized_query = product_query.strip()
            evidence: tuple[ToolEvidence, ...]
            if not records:
                outcome: Literal["found", "ambiguous", "not_found"] = "not_found"
                data = ProductSuggestionSearchData(
                    product_query=normalized_query,
                    status="not_found",
                    outcome=outcome,
                    candidates=[],
                )
                evidence = ()
            elif len(records) > 1:
                outcome = "ambiguous"
                data = ProductSuggestionSearchData(
                    product_query=normalized_query,
                    status="ambiguous",
                    outcome=outcome,
                    candidates=candidates,
                )
                # Candidate rows are intentionally not treated as factual
                # evidence. The user must choose before a complete card is
                # exposed to the compiler and judge.
                evidence = ()
            else:
                record = records[0]
                selection_id = create_selection_id(record)
                detail = tool_context.repository.get_product_suggestion_detail(
                    tool_context.authorized,
                    record.suggestion_id,
                )
                if detail is None or selection_fingerprint(
                    detail
                ) != selection_fingerprint(record):
                    outcome = "not_found"
                    data = ProductSuggestionSearchData(
                        product_query=normalized_query,
                        status="not_found",
                        outcome=outcome,
                        candidates=[],
                    )
                    evidence = ()
                else:
                    detail_data = build_detail_data(
                        detail,
                        selection_ref=create_selection_ref(record),
                        selection_id=selection_id,
                        manager=(
                            tool_context.authorized.role_code == MANAGER_ROLE_CODE
                        ),
                    )
                    outcome = "found"
                    data = ProductSuggestionSearchData(
                        product_query=normalized_query,
                        status="unique",
                        outcome=outcome,
                        suggestion=detail_data.card,
                        triage=detail_data.triage,
                        candidates=[],
                    )
                    unique_evidence = [detail_evidence(detail, detail_data)]
                    if detail_data.triage is not None:
                        unique_evidence.append(
                            triage_evidence(detail, detail_data.triage)
                        )
                    evidence = tuple(unique_evidence)
            warnings = (
                (
                    ToolWarning(
                        code="NO_AUTHORIZED_SUGGESTION",
                        message="Nenhuma sugestão autorizada correspondeu à busca.",
                    ),
                )
                if outcome == "not_found"
                else (
                    ToolWarning(
                        code="MULTIPLE_MATCHES",
                        message="Mais de uma sugestão correspondeu à busca.",
                    ),
                )
                if outcome == "ambiguous"
                else ()
            )
            logger.info(
                "product_workflow_lookup_completed",
                extra={
                    "event": "tool_lookup_completed",
                    "outcome": outcome,
                    "results_count": len(records),
                    "no_results": not records,
                },
            )
            response = create_compose_response(
                intent=(
                    "explain_unique_suggestion"
                    if outcome == "found"
                    else "select_product_suggestion"
                ),
                must_include=(
                    ["/product_query", "/status", "/suggestion"]
                    if outcome == "found"
                    else ["/product_query", "/status", "/outcome", "/candidates"]
                ),
                constraints=(
                    ("Não selecione uma opção sem confirmação do usuário.",)
                    if outcome == "ambiguous"
                    else ()
                ),
            )
            result = (
                partial_result(
                    response=DirectResponse(
                        content=ResponseContent(
                            text=(
                                "Encontrei mais de uma sugestão para esse produto. "
                                "Qual opção você deseja consultar?"
                            )
                        )
                    ),
                    data=data,
                    meta=metadata(
                        tool_name="get_suggestion_for_product",
                        context=tool_context.authorized,
                    ),
                    extras=ToolResultExtras(
                        evidence=evidence,
                        warnings=warnings,
                    ),
                    next_step="clarification",
                )
                if outcome == "ambiguous"
                else direct_success(
                    content=ResponseContent(
                        text=(
                            "Não há cards ou sugestões válidas para esse produto."
                        )
                    ),
                    data=data,
                    meta=metadata(
                        tool_name="get_suggestion_for_product",
                        context=tool_context.authorized,
                    ),
                    extras=ToolResultExtras(warnings=warnings),
                )
                if outcome == "not_found"
                else compose_success(
                    response=response,
                    data=data,
                    meta=metadata(
                        tool_name="get_suggestion_for_product",
                        context=tool_context.authorized,
                    ),
                    extras=ToolResultExtras(
                        evidence=evidence,
                        warnings=warnings,
                    ),
                )
            )
            return serialize_for_agent(result)
        except Exception as exc:
            logger.warning(
                "product_workflow_lookup_failed",
                extra={
                    "event": "tool_lookup_failed",
                    "error_type": type(exc).__name__,
                },
            )
            return failure(
                tool_name="get_suggestion_for_product",
                context=tool_context.authorized,
                error=exc,
            )

    @tool
    def get_suggestion_detail(selection_id: str) -> str:
        """Retorna o card autorizado após revalidar a seleção no servidor."""

        try:
            suggestion_id, expected_fingerprint = parse_selection_token(selection_id)
            detail = tool_context.repository.get_product_suggestion_detail(
                tool_context.authorized,
                suggestion_id,
            )
            if detail is None:
                return not_found(
                    tool_name="get_suggestion_detail",
                    context=tool_context.authorized,
                )
            if (
                expected_fingerprint is not None
                and selection_fingerprint(detail) != expected_fingerprint
            ):
                return not_found(
                    tool_name="get_suggestion_detail",
                    context=tool_context.authorized,
                )
            data = build_detail_data(
                detail,
                selection_ref=str(detail.suggestion_id),
                selection_id=selection_id,
                manager=tool_context.authorized.role_code == MANAGER_ROLE_CODE,
            )
            evidence = [detail_evidence(detail, data)]
            if data.triage is not None:
                evidence.append(triage_evidence(detail, data.triage))
            result = compose_success(
                response=create_compose_response(
                    intent=(
                        "explain_suggestion_for_manager"
                        if data.visibility == "manager"
                        else "explain_suggestion_for_employee"
                    ),
                    must_include=["/card", "/triage"],
                ),
                data=data,
                meta=metadata(
                    tool_name="get_suggestion_detail",
                    context=tool_context.authorized,
                ),
                extras=ToolResultExtras(evidence=tuple(evidence)),
            )
            return serialize_for_agent(result)
        except ValueError:
            return selection_error(
                tool_name="get_suggestion_detail",
                context=tool_context.authorized,
            )
        except Exception as exc:
            return failure(
                tool_name="get_suggestion_detail",
                context=tool_context.authorized,
                error=exc,
            )

    @tool
    def list_suggestions(
        suggestion_type: Literal["ORDER", "PROMOTION"],
        page_size: int = DEFAULT_SUGGESTION_PAGE_SIZE,
        cursor: str | None = None,
    ) -> str:
        """Lista uma página de sugestões visíveis para o usuário autenticado."""

        try:
            page = tool_context.repository.list_product_suggestions(
                tool_context.authorized,
                suggestion_type,
                page_size=page_size,
                cursor=cursor,
            )
            candidates = [
                _candidate(record, index)
                for index, record in enumerate(page.suggestions, start=1)
            ]
            data = SuggestionListData(
                suggestion_type=suggestion_type,
                candidates=candidates,
                next_cursor=page.next_cursor,
            )
            evidence = (
                tuple(
                    candidate_evidence(record, candidate)
                    for record, candidate in zip(
                        page.suggestions, candidates, strict=True
                    )
                )
                if candidates
                else (
                    (
                        no_more_suggestions_page_evidence(suggestion_type),
                    )
                    if cursor is not None
                    else (no_suggestions_for_type_evidence(suggestion_type),)
                )
            )
            warnings: tuple[ToolWarning, ...] = ()
            if page.next_cursor is not None:
                warnings = (
                    ToolWarning(
                        code="MORE_RESULTS_AVAILABLE",
                        message=(
                            "Há mais sugestões visíveis. Continue usando "
                            "next_cursor antes de afirmar que a lista completa."
                        ),
                    ),
                )
            elif cursor is not None and not candidates:
                warnings = (
                    ToolWarning(
                        code="END_OF_RESULTS",
                        message="Não há mais sugestões após este cursor.",
                    ),
                )
            extras = ToolResultExtras(
                evidence=evidence,
                warnings=warnings,
            )
            response = create_compose_response(
                intent="list_visible_product_suggestions",
                must_include=["/suggestion_type", "/candidates", "/next_cursor"],
                constraints=(
                    (
                        "Informe que não há mais sugestões após o cursor."
                        if cursor is not None and not candidates
                        else (
                            "Informe que não há sugestões desse tipo no escopo "
                            "autorizado."
                            if not candidates
                            else "Mostre apenas o resumo dos candidatos. Se o "
                            "usuário pedir detalhes de um item, aguarde a "
                            "escolha e chame get_suggestion_detail com sua "
                            "selection_id."
                        )
                    ),
                ),
            )
            result = (
                partial_result(
                    response=response,
                    data=data,
                    meta=metadata(
                        tool_name="list_suggestions",
                        context=tool_context.authorized,
                    ),
                    extras=extras,
                )
                if page.next_cursor is not None
                else compose_success(
                    response=response,
                    data=data,
                    meta=metadata(
                        tool_name="list_suggestions",
                        context=tool_context.authorized,
                    ),
                    extras=extras,
                )
            )
            return serialize_for_agent(result)
        except Exception as exc:
            return failure(
                tool_name="list_suggestions",
                context=tool_context.authorized,
                error=exc,
            )

    @tool
    def get_promotion_by_expiration(
        direction: Literal["nearest", "longest"],
        page_size: int = MAX_PROMOTION_TIE_PAGE_SIZE,
        cursor: str | None = None,
    ) -> str:
        """Finds the nearest/longest-valid promotion, preserving expiry ties."""

        try:
            page = tool_context.repository.find_promotions_by_expiration(
                tool_context.authorized,
                direction,
                page_size=page_size,
                cursor=cursor,
            )
            records = page.suggestions
            candidates = [
                _candidate(record, index)
                for index, record in enumerate(records, start=1)
            ]
            valid_until = (
                records[0].promotion_valid_until if records else None
            )

            if not records:
                is_continuation = cursor is not None
                data = PromotionExpirationData(
                    direction=direction,
                    outcome="not_found",
                    promotion_valid_until=None,
                    candidates=[],
                    detail=None,
                    next_cursor=None,
                )
                result = compose_success(
                    response=create_compose_response(
                        intent=(
                            "no_more_tied_promotions"
                            if is_continuation
                            else "no_valid_promotion_by_expiration"
                        ),
                        must_include=["/direction", "/outcome", "/candidates"],
                        constraints=(
                            (
                                "Informe que não há mais promoções empatadas "
                                "após este cursor. Preserve as opções já listadas."
                                if is_continuation
                                else "Informe que não há promoção válida com a "
                                "validade solicitada no escopo autorizado."
                            ),
                        ),
                    ),
                    data=data,
                    meta=metadata(
                        tool_name="get_promotion_by_expiration",
                        context=tool_context.authorized,
                    ),
                    extras=ToolResultExtras(
                        evidence=(
                            (
                                no_more_promotions_page_evidence(direction),
                            )
                            if cursor is not None
                            else (no_valid_promotion_evidence(direction),)
                        ),
                        warnings=(
                            ToolWarning(
                                code=(
                                    "NO_MORE_TIED_PROMOTIONS"
                                    if is_continuation
                                    else "NO_VALID_PROMOTION"
                                ),
                                message=(
                                    "Não há mais promoções empatadas após este cursor."
                                    if is_continuation
                                    else "Não há promoções válidas com essa "
                                    "ordenação de validade no escopo autorizado."
                                ),
                            ),
                        ),
                    ),
                )
                return serialize_for_agent(result)

            if len(records) == 1 and page.next_cursor is None and cursor is None:
                detail_result = _get_detail_data(
                    tool_context,
                    records[0],
                    selection_id=candidates[0].selection_id,
                )
                if detail_result is None:
                    return not_found(
                        tool_name="get_promotion_by_expiration",
                        context=tool_context.authorized,
                    )
                detail_record, detail = detail_result
                data = PromotionExpirationData(
                    direction=direction,
                    outcome="found",
                    promotion_valid_until=valid_until,
                    candidates=candidates,
                    detail=detail,
                    next_cursor=None,
                )
                result = compose_success(
                    response=create_compose_response(
                        intent="explain_extreme_validity_promotion",
                        must_include=["/promotion_valid_until", "/detail/card"],
                    ),
                    data=data,
                    meta=metadata(
                        tool_name="get_promotion_by_expiration",
                        context=tool_context.authorized,
                    ),
                    extras=_detail_evidence(detail_record, detail),
                )
                return serialize_for_agent(result)

            data = PromotionExpirationData(
                direction=direction,
                outcome="ambiguous",
                promotion_valid_until=valid_until,
                candidates=candidates,
                detail=None,
                next_cursor=page.next_cursor,
            )
            warnings = [
                ToolWarning(
                    code="MULTIPLE_PROMOTIONS_SAME_VALIDITY",
                    message=(
                        "Mais de uma promoção compartilha a validade extrema; "
                        "é necessária a escolha explícita do usuário."
                    ),
                )
            ]
            if page.next_cursor is not None:
                warnings.append(
                    ToolWarning(
                        code="MORE_TIED_PROMOTIONS_AVAILABLE",
                        message=(
                            "Há mais promoções empatadas. Consulte as páginas "
                            "seguintes antes de solicitar a escolha."
                        ),
                    )
                )
            result = partial_result(
                response=create_compose_response(
                    intent="select_promotion_by_validity",
                    must_include=[
                        "/direction",
                        "/promotion_valid_until",
                        "/candidates",
                        "/next_cursor",
                    ],
                    constraints=(
                        "Mostre os candidatos empatados numerados e aguarde a "
                        "escolha explícita. Se next_cursor não for nulo, busque "
                        "as demais opções antes de pedir a escolha. Depois chame "
                        "get_suggestion_detail com a selection_id escolhida.",
                    ),
                ),
                data=data,
                meta=metadata(
                    tool_name="get_promotion_by_expiration",
                    context=tool_context.authorized,
                ),
                extras=ToolResultExtras(
                    evidence=tuple(
                        candidate_evidence(record, candidate)
                        for record, candidate in zip(records, candidates, strict=True)
                    ),
                    warnings=tuple(warnings),
                ),
            )
            return serialize_for_agent(result)
        except Exception as exc:
            return failure(
                tool_name="get_promotion_by_expiration",
                context=tool_context.authorized,
                error=exc,
            )

    return [
        get_suggestion_for_product,
        get_suggestion_detail,
        list_suggestions,
        get_promotion_by_expiration,
    ]


def _candidate(
    record: ProductSuggestionSearchRecord,
    position: int,
) -> ProductSuggestionCandidate:
    selection_id = create_selection_id(record)
    return ProductSuggestionCandidate(
        position=position,
        selection_id=selection_id,
        selection_ref=create_selection_ref(record),
        suggestion_id=record.suggestion_id,
        product_id=record.product_id,
        product_name=record.product_name,
        category_name=record.category_name,
        sku=record.sku,
        store_name=record.store_name,
        suggestion_type=record.suggestion_type,
        suggestion_status=record.suggestion_status,
        promotion_valid_until=record.promotion_valid_until,
    )


def _get_detail_data(
    tool_context: ProductWorkflowToolContext,
    record: ProductSuggestionSearchRecord,
    *,
    selection_id: str,
) -> tuple[ProductSuggestionDetailRecord, SuggestionDetailData] | None:
    detail_record = tool_context.repository.get_product_suggestion_detail(
        tool_context.authorized,
        record.suggestion_id,
    )
    if (
        detail_record is None
        or selection_fingerprint(detail_record) != selection_fingerprint(record)
    ):
        return None
    return (
        detail_record,
        build_detail_data(
            detail_record,
            selection_ref=create_selection_ref(record),
            selection_id=selection_id,
            manager=tool_context.authorized.role_code == MANAGER_ROLE_CODE,
        ),
    )


def _detail_evidence(
    detail_record: ProductSuggestionDetailRecord,
    data: SuggestionDetailData,
) -> ToolResultExtras:
    evidence: list[ToolEvidence] = [detail_evidence(detail_record, data)]
    if data.triage is not None:
        evidence.append(triage_evidence(detail_record, data.triage))
    return ToolResultExtras(evidence=tuple(evidence))
