"""Evidence projections for Product Workflow tool results."""

from __future__ import annotations

import hashlib

from src.agents.product_workflow.models import (
    ProductSuggestionCandidate,
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchRecord,
    SuggestionDetailData,
    SuggestionTriageData,
)
from src.agents.schemas.tool_result import ToolEvidence


def _absence_evidence(*, source_id: str, content: str) -> ToolEvidence:
    digest = hashlib.sha256(source_id.encode()).hexdigest()[:16]
    return ToolEvidence(
        evidence_id=f"product-workflow:empty:{digest}",
        source_type="product_workflow",
        source_id=source_id,
        content=content,
        metadata={"outcome": "not_found", "provenance": "postgresql_read"},
    )


def no_matching_suggestion_evidence(product_query: str) -> ToolEvidence:
    digest = hashlib.sha256(product_query.strip().casefold().encode()).hexdigest()[:12]
    return _absence_evidence(
        source_id=f"authorized_product_suggestion_search:{digest}",
        content=(
            "A consulta autenticada não encontrou cards ou sugestões válidas "
            "do tipo pedido ou promoção para o termo consultado no escopo "
            "autorizado."
        ),
    )


def no_suggestions_for_type_evidence(suggestion_type: str) -> ToolEvidence:
    label = "pedido" if suggestion_type == "ORDER" else "promoção"
    return _absence_evidence(
        source_id=f"authorized_suggestion_list:{suggestion_type.lower()}",
        content=(
            f"A consulta autenticada não encontrou sugestões válidas do tipo "
            f"{label} no escopo autorizado."
        ),
    )


def no_more_suggestions_page_evidence(suggestion_type: str) -> ToolEvidence:
    return _absence_evidence(
        source_id=f"authorized_suggestion_page_end:{suggestion_type.lower()}",
        content=(
            "A página solicitada não contém mais sugestões após o cursor no "
            "escopo autorizado."
        ),
    )


def no_valid_promotion_evidence(direction: str) -> ToolEvidence:
    description = "mais próxima" if direction == "nearest" else "mais longa"
    return _absence_evidence(
        source_id=f"authorized_promotion_expiration:{direction}",
        content=(
            "A consulta autenticada não encontrou promoções válidas com data "
            f"de validade {description} no escopo autorizado."
        ),
    )


def no_more_promotions_page_evidence(direction: str) -> ToolEvidence:
    return _absence_evidence(
        source_id=f"authorized_promotion_page_end:{direction}",
        content=(
            "A página solicitada não contém mais promoções empatadas após o "
            "cursor no escopo autorizado."
        ),
    )


def candidate_evidence(
    record: ProductSuggestionSearchRecord,
    candidate: ProductSuggestionCandidate,
) -> ToolEvidence:
    return ToolEvidence(
        evidence_id=f"product-search:suggestion:{record.suggestion_id}",
        source_type="product_workflow",
        source_id=f"postgresql:suggestion:{record.suggestion_id}",
        content=candidate.model_dump_json(),
        metadata={
            "entity_type": "suggestion_candidate",
            "suggestion_id": str(record.suggestion_id),
            "product_id": str(record.product_id),
            "store_id": str(record.store_id),
        },
    )


def detail_evidence(
    detail: ProductSuggestionDetailRecord,
    data: SuggestionDetailData,
) -> ToolEvidence:
    return ToolEvidence(
        evidence_id=f"suggestion-detail:{detail.suggestion_id}",
        source_type="product_workflow",
        source_id=f"postgresql:suggestion:{detail.suggestion_id}",
        content=data.card.model_dump_json(),
        metadata={
            "entity_type": "suggestion_card",
            "suggestion_id": str(detail.suggestion_id),
            "product_id": str(detail.product_id),
            "store_id": str(detail.store_id),
        },
    )


def triage_evidence(
    detail: ProductSuggestionDetailRecord,
    triage: SuggestionTriageData,
) -> ToolEvidence:
    return ToolEvidence(
        evidence_id=f"suggestion-triage:{detail.suggestion_id}",
        source_type="product_workflow",
        source_id=f"postgresql:suggestion_triage:{detail.suggestion_id}",
        content=triage.model_dump_json(),
        metadata={
            "entity_type": "suggestion_triage",
            "suggestion_id": str(detail.suggestion_id),
            "store_id": str(detail.store_id),
        },
    )
