"""Evidence projections for Product Workflow tool results."""

from __future__ import annotations

from src.agents.product_workflow.models import (
    ProductSuggestionCandidate,
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchRecord,
    SuggestionDetailData,
    SuggestionTriageData,
)
from src.agents.schemas.tool_result import ToolEvidence


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
