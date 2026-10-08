"""Selection reference parsing for Product Workflow tools."""

from __future__ import annotations

from src.agents.product_workflow.models import ProductSuggestionSearchRecord


def create_selection_ref(record: ProductSuggestionSearchRecord) -> str:
    """Use the suggestion ID as a selector, never as authorization."""

    return str(record.suggestion_id)


def parse_selection_ref(selection_ref: str) -> int:
    """Parse a positive suggestion ID supplied by the second tool."""

    try:
        suggestion_id = int(selection_ref.strip())
    except AttributeError, TypeError, ValueError:
        raise ValueError("Referência de seleção inválida") from None
    if suggestion_id < 1:
        raise ValueError("Referência de seleção inválida")
    return suggestion_id
