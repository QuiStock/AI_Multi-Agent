from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from langchain_core.tools import BaseTool, tool

from src.agents.product_workflow.filters import MANAGER_ROLE_ID
from src.agents.product_workflow.models import (
    ProductSuggestionCandidate,
    ProductSuggestionSearchData,
    ProductWorkflowContext,
)
from src.agents.product_workflow.repository import ProductWorkflowRepository
from src.agents.schemas.tool_result import ToolWarning
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_compose_response,
    partial_result,
)

from .errors import failure, metadata, not_found, selection_error
from .evidence import candidate_evidence, detail_evidence, triage_evidence
from .projections import build_detail_data
from .selection import create_selection_ref, parse_selection_ref


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
        """Busca sugestões autorizadas e sempre retorna candidatos numerados."""

        try:
            records = tool_context.repository.search_product_suggestions(
                tool_context.authorized,
                product_query,
                limit=6,
            )
            candidates = [
                ProductSuggestionCandidate(
                    position=index,
                    selection_ref=create_selection_ref(record),
                    product_name=record.product_name,
                    category_name=record.category_name,
                    sku=record.sku,
                    store_name=record.store_name,
                    suggestion_type=record.suggestion_type,
                    suggestion_status=record.suggestion_status,
                )
                for index, record in enumerate(records, start=1)
            ]
            outcome: Literal["found", "ambiguous", "not_found"] = (
                "not_found"
                if not candidates
                else "found"
                if len(candidates) == 1
                else "ambiguous"
            )
            data = ProductSuggestionSearchData(
                product_query=product_query.strip(),
                outcome=outcome,
                candidates=candidates,
            )
            evidence = tuple(
                candidate_evidence(record, candidate)
                for record, candidate in zip(records, candidates, strict=True)
            )
            warnings = (
                (
                    ToolWarning(
                        code="NO_MATCHING_PRODUCT",
                        message="Nenhuma sugestão correspondeu à busca.",
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
            response = create_compose_response(
                intent="select_product_suggestion",
                must_include=["/product_query", "/outcome", "/candidates"],
                constraints=(
                    ("Não selecione uma opção sem confirmação do usuário.",)
                    if outcome == "ambiguous"
                    else ()
                ),
            )
            result = (
                partial_result(
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
                if outcome == "ambiguous"
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
            return failure(
                tool_name="get_suggestion_for_product",
                context=tool_context.authorized,
                error=exc,
            )

    @tool
    def get_suggestion_detail(selection_ref: str) -> str:
        """Retorna o card autorizado da sugestão selecionada."""

        try:
            suggestion_id = parse_selection_ref(selection_ref)
            detail = tool_context.repository.get_product_suggestion_detail(
                tool_context.authorized,
                suggestion_id,
            )
            if detail is None:
                return not_found(
                    tool_name="get_suggestion_detail",
                    context=tool_context.authorized,
                )
            data = build_detail_data(
                detail,
                selection_ref=selection_ref,
                manager=tool_context.authorized.role_id == MANAGER_ROLE_ID,
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

    return [get_suggestion_for_product, get_suggestion_detail]
