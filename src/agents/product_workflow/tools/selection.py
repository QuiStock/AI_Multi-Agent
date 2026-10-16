"""Selection reference parsing for Product Workflow tools."""

from __future__ import annotations

import hashlib
import re

from src.agents.product_workflow.models import (
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchRecord,
)


def create_selection_ref(record: ProductSuggestionSearchRecord) -> str:
    """Keep the legacy reference stable for existing local consumers."""

    return str(record.suggestion_id)


def create_selection_id(record: ProductSuggestionSearchRecord) -> str:
    """Bind the selector to the candidate projection without granting access."""

    return f"candidate-{record.suggestion_id}-{selection_fingerprint(record)}"


def selection_fingerprint(
    record: ProductSuggestionSearchRecord | ProductSuggestionDetailRecord,
) -> str:
    """Fingerprint safe candidate identity fields for cross-turn revalidation."""

    status = getattr(record, "suggestion_status", None) or getattr(
        record,
        "status",
        "",
    )
    payload = "|".join(
        str(value)
        for value in (
            record.product_id,
            record.store_id,
            record.product_name,
            record.category_name or "",
            record.sku,
            record.store_name,
            record.suggestion_type,
            status,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def parse_selection_token(selection_id: str) -> tuple[int, str | None]:
    """Parse a current fingerprinted selector or a legacy decimal reference."""

    try:
        normalized = selection_id.strip()
    except AttributeError, TypeError:
        raise ValueError("Referência de seleção inválida") from None

    if normalized.startswith("candidate-"):
        parts = normalized.split("-")
        if len(parts) not in {2, 3}:
            raise ValueError("Referência de seleção inválida")
        normalized_id = parts[1]
        fingerprint = parts[2] if len(parts) == 3 else None
        if (
            fingerprint is not None
            and re.fullmatch(r"[0-9a-f]{16}", fingerprint) is None
        ):
            raise ValueError("Referência de seleção inválida")
    else:
        normalized_id = normalized
        fingerprint = None

    try:
        suggestion_id = int(normalized_id)
    except ValueError:
        raise ValueError("Referência de seleção inválida") from None
    if suggestion_id < 1:
        raise ValueError("Referência de seleção inválida")
    return suggestion_id, fingerprint


def parse_selection_id(selection_id: str) -> int:
    """Parse a current candidate selector or a legacy decimal reference."""

    return parse_selection_token(selection_id)[0]


def parse_selection_ref(selection_ref: str) -> int:
    """Compatibility alias for callers that still send ``selection_ref``."""

    return parse_selection_id(selection_ref)
