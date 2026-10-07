"""Role-specific projections returned by Product Workflow tools."""

from __future__ import annotations

from src.agents.product_workflow.models import (
    ProductSuggestionDetailRecord,
    SuggestionCardData,
    SuggestionDetailData,
    SuggestionTriageData,
)


def build_detail_data(
    detail: ProductSuggestionDetailRecord,
    *,
    selection_ref: str,
    manager: bool,
) -> SuggestionDetailData:
    """Build the public card and expose triage only to managers."""

    card = SuggestionCardData(
        selection_ref=selection_ref,
        product_id=detail.product_id,
        product_name=detail.product_name,
        category_name=detail.category_name,
        sku=detail.sku,
        store_id=detail.store_id,
        store_name=detail.store_name,
        suggestion_id=detail.suggestion_id,
        suggestion_type=detail.suggestion_type,
        origin=detail.origin,
        status=detail.status,
        ml_batch_count=detail.ml_batch_count,
        current_batch_count=detail.current_batch_count,
        effective_batch_count=(detail.current_batch_count or detail.ml_batch_count),
        ml_discount_percentage=detail.ml_discount_percentage,
        current_discount_percentage=detail.current_discount_percentage,
        effective_discount_percentage=(
            detail.current_discount_percentage
            if detail.current_discount_percentage is not None
            else detail.ml_discount_percentage
        ),
        reference_sale_price=detail.reference_sale_price,
        promotional_price=detail.promotional_price,
        promotion_valid_from=detail.promotion_valid_from,
        promotion_valid_until=detail.promotion_valid_until,
        physical_expiration_date=detail.physical_expiration_date,
        available_for_triage=detail.available_for_triage,
        created_at=detail.created_at,
        updated_at=detail.updated_at,
    )
    triage = None
    if manager and detail.last_action is not None and detail.triage_updated_at:
        triage = SuggestionTriageData(
            employee_id=detail.employee_id,
            employee_name=detail.employee_name,
            last_action=detail.last_action,
            forwarded_at=detail.forwarded_at,
            updated_at=detail.triage_updated_at,
        )
    return SuggestionDetailData(
        visibility="manager" if manager else "employee",
        card=card,
        triage=triage,
    )
