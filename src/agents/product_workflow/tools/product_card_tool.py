from __future__ import annotations

import hashlib
from typing import Any, Literal
from uuid import uuid4

from langchain_core.tools import BaseTool, StructuredTool
from psycopg import errors as psycopg_errors
from psycopg_pool import PoolTimeout

from src.agents.product_workflow.schemas import (
    ProductCard,
    ProductLookupCandidate,
    ProductLookupData,
)
from src.agents.product_workflow.tools.product_card_repository import (
    ProductCardRepository,
)
from src.agents.product_workflow.tools.schemas import ProductCardLookupArguments
from src.agents.schemas.tool_result import ToolEvidence, ToolWarning
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    ToolResultExtras,
    compose_success,
    create_compose_response,
    create_tool_error,
    create_tool_metadata,
    partial_result,
    tool_error,
)


def create_product_card_tool(
    *, repository: ProductCardRepository, email: str, role_id: int, request_id: str
) -> BaseTool:
    """Bind server-authenticated identity; the model controls only product text."""

    def lookup(product_query: str) -> str:
        return _lookup_product_cards(
            repository=repository,
            email=email,
            role_id=role_id,
            request_id=request_id,
            product_query=product_query,
        )

    return StructuredTool.from_function(
        func=lookup,
        name="product_card_lookup",
        args_schema=ProductCardLookupArguments,
        description=(
            "Busca sugestões atuais visíveis ao usuário autenticado para um "
            "produto por nome. Não aceita email, cargo, loja, SQL nem IDs."
        ),
    )


def _lookup_product_cards(
    *,
    repository: ProductCardRepository,
    email: str,
    role_id: int,
    request_id: str,
    product_query: str,
) -> str:
    metadata = create_tool_metadata(
        tool_name="product_card_lookup",
        tool_version="1.0.0",
        tool_call_id=str(uuid4()),
        trace_id=request_id,
    )
    try:
        cards = repository.search(
            email=email, role_id=role_id, product_query=product_query
        )
        result = _build_product_result(cards=cards, metadata=metadata)
    except Exception as error:
        return serialize_for_agent(
            tool_error(error=_lookup_failure(error), meta=metadata)
        )
    return serialize_for_agent(result)


def _build_product_result(cards: list[ProductCard], metadata: Any) -> Any:
    outcome: Literal["found", "ambiguous", "not_found"] = (
        "not_found" if not cards else "found" if len(cards) == 1 else "ambiguous"
    )
    if outcome == "ambiguous":
        data = ProductLookupData(
            outcome=outcome,
            candidates=[
                ProductLookupCandidate(
                    candidate_ref=hashlib.sha256(
                        str(card.product_id).encode()
                    ).hexdigest()[:12],
                    product_name=card.product_name,
                    category_name=card.category_name,
                    sku=card.sku,
                )
                for card in cards
            ],
        )
    else:
        data = ProductLookupData(outcome=outcome, cards=cards)
    evidence = _product_evidence(cards=cards, data=data, outcome=outcome)
    if outcome == "ambiguous":
        return partial_result(
            response=create_compose_response(
                intent="clarify_product_selection",
                constraints=(
                    "Não selecione uma opção sem confirmação inequívoca do usuário.",
                ),
            ),
            data=data,
            meta=metadata,
            extras=ToolResultExtras(
                evidence=tuple(evidence),
                warnings=(
                    ToolWarning(
                        code="MULTIPLE_MATCHES",
                        message="Mais de um produto correspondeu à busca.",
                    ),
                ),
            ),
        )
    return compose_success(
        response=create_compose_response(intent="explain_product_card"),
        data=data,
        meta=metadata,
        extras=ToolResultExtras(evidence=tuple(evidence)),
    )


def _product_evidence(
    *,
    cards: list[ProductCard],
    data: ProductLookupData,
    outcome: Literal["found", "ambiguous", "not_found"],
) -> list[ToolEvidence]:
    evidence = (
        [
            ToolEvidence(
                evidence_id=(
                    "product_"
                    + hashlib.sha256(
                        str(card.suggestion_id or card.product_id).encode()
                    ).hexdigest()[:16]
                ),
                source_type="product_card_query",
                source_id=str(card.suggestion_id or card.product_id),
                content=card.model_dump_json(),
                metadata={"provenance": "postgresql_read"},
            )
            for card in cards
        ]
        if outcome == "found"
        else []
    )
    if outcome == "ambiguous":
        evidence.extend(
            ToolEvidence(
                evidence_id=f"product_candidate_{candidate.candidate_ref}",
                source_type="product_card_query",
                source_id=candidate.candidate_ref,
                content=candidate.model_dump_json(),
                metadata={"provenance": "postgresql_read"},
            )
            for candidate in data.candidates
        )
    if outcome == "not_found":
        evidence.append(
            ToolEvidence(
                evidence_id="product_query_empty_" + uuid4().hex[:12],
                source_type="product_card_query",
                source_id="authorized_lookup",
                content=(
                    "A consulta autorizada não retornou card vigente "
                    "para o nome pesquisado."
                ),
                metadata={"outcome": "not_found"},
            )
        )
    return evidence


def _lookup_failure(error: Exception) -> Any:
    if isinstance(error, PermissionError):
        return create_tool_error(
            code="PRODUCT_LOOKUP_FORBIDDEN",
            category="authorization",
            message="Cargo sem acesso à consulta de produtos.",
        )
    if isinstance(error, ValueError):
        return create_tool_error(
            code="PRODUCT_LOOKUP_INVALID",
            category="validation",
            message="A consulta de produto é inválida.",
        )
    if isinstance(error, (TimeoutError, PoolTimeout, psycopg_errors.QueryCanceled)):
        return create_tool_error(
            code="PRODUCT_LOOKUP_TIMEOUT",
            category="timeout",
            message="A consulta de produtos excedeu o tempo limite.",
            retryable=True,
        )
    return create_tool_error(
        code="PRODUCT_LOOKUP_UNAVAILABLE",
        category="dependency",
        message="A consulta de produtos está temporariamente indisponível.",
        retryable=True,
    )
