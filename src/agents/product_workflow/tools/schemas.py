"""Payloads and helpers returned by the Product Workflow tools."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from src.agents.product_workflow.contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionListingRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
    SuggestionType,
)
from src.agents.product_workflow.filters import (
    MAX_PRODUCT_SEARCH_PAGE,
    PRODUCT_SEARCH_PAGE_SIZE,
)
from src.agents.schemas.tool_result import (
    ToolErrorCategory,
    ToolEvidence,
    ToolMetadata,
    ToolResult,
)
from src.agents.tooling.result_adapter import serialize_for_agent
from src.agents.tooling.result_factory import (
    create_tool_error,
    create_tool_metadata,
    tool_error,
)

LookupOutcome = Literal["unique", "ambiguous", "not_found"]


class SuggestionCandidateData(BaseModel):
    """Numbered option shown before the user chooses a suggestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(
        ge=1,
        le=MAX_PRODUCT_SEARCH_PAGE * PRODUCT_SEARCH_PAGE_SIZE,
    )
    selection_id: str = Field(min_length=1, max_length=240)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    suggestion_type: SuggestionType


class SuggestionCardData(BaseModel):
    """Public suggestion card. Absent commercial fields are omitted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selection_id: str = Field(min_length=1, max_length=240)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    suggestion_type: SuggestionType
    ml_batch_count: int | None = Field(default=None, gt=0)
    current_batch_count: int | None = Field(default=None, gt=0)
    ml_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    current_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    promotional_price: float | None = Field(default=None, ge=0)
    promotion_valid_from: date | None = None
    promotion_valid_until: date | None = None
    physical_expiration_date: date | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ProductSearchData(BaseModel):
    """One page from the authorized product-name or SKU search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_query: str = Field(min_length=1, max_length=200)
    page: int = Field(ge=1)
    has_more: bool = False
    status: LookupOutcome
    suggestion: SuggestionCardData | None = None
    candidates: list[SuggestionCandidateData] | None = None


class SuggestionDetailData(BaseModel):
    """Revalidated card for the suggestion the user selected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["unique"] = "unique"
    visibility: Literal["manager", "employee"]
    card: SuggestionCardData


class SuggestionListData(BaseModel):
    """One page of ORDER or PROMOTION suggestions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suggestion_types: list[SuggestionType] = Field(min_length=1, max_length=2)
    page: int = Field(ge=1)
    has_more: bool = False
    status: LookupOutcome
    suggestion: SuggestionCardData | None = None
    candidates: list[SuggestionCandidateData] | None = None


class PromotionExpirationData(BaseModel):
    """Extreme validity, or promotions valid through an until date."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Literal["nearest", "longest"] | None = None
    until: date | None = None
    page: int = Field(ge=1)
    has_more: bool = False
    status: LookupOutcome
    promotion_valid_until: date | None = None
    suggestion: SuggestionCardData | None = None
    candidates: list[SuggestionCandidateData] | None = None


SelectionRecord = (
    ProductSuggestionSearchRecord
    | ProductSuggestionListingRecord
    | ProductSuggestionDetailRecord
)
OnToolResult = Callable[[dict[str, Any]], None]


def public_dict(model: BaseModel) -> dict[str, Any]:
    """Drop nulls and empty lists so the tool payload only contains facts."""

    payload = model.model_dump(mode="json", exclude_none=True)
    return {key: value for key, value in payload.items() if value != []}


def suggestion_card(
    record: ProductSuggestionDetailRecord,
    *,
    selection_id: str,
) -> SuggestionCardData:
    """Project a database row into the public card."""

    values: dict[str, Any] = {
        "selection_id": selection_id,
        "product_name": record.product_name,
        "sku": record.sku,
        "suggestion_type": record.suggestion_type,
        "created_at": record.created_at,
    }
    optional = {
        "category_name": record.category_name,
        "ml_discount_percentage": record.ml_discount_percentage,
        "current_discount_percentage": record.current_discount_percentage,
        "promotional_price": record.promotional_price,
        "promotion_valid_from": record.promotion_valid_from,
        "promotion_valid_until": record.promotion_valid_until,
        "physical_expiration_date": record.physical_expiration_date,
        "updated_at": record.updated_at,
    }
    if record.suggestion_type == "ORDER":
        optional["ml_batch_count"] = record.ml_batch_count
        optional["current_batch_count"] = record.current_batch_count
    values.update({key: value for key, value in optional.items() if value is not None})
    return SuggestionCardData.model_validate(values)


def selection_fingerprint(record: SelectionRecord) -> str:
    """Fingerprint the fields that identify a candidate across tools."""

    status = getattr(record, "suggestion_status", None) or getattr(record, "status", "")
    payload = "|".join(
        str(value)
        for value in (
            record.suggestion_id,
            record.product_id,
            record.product_name,
            record.category_name or "",
            record.sku,
            record.suggestion_type,
            status,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def legacy_selection_fingerprint(
    record: ProductSuggestionListingRecord | ProductSuggestionDetailRecord,
) -> str:
    """Accept selectors issued before the compact candidate projection."""

    status = getattr(record, "suggestion_status", None) or getattr(record, "status", "")
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


def page_position(page: int, index: int) -> int:
    """Return the 1-based number that continues from the previous page.

    ``index`` is 0-based within the current page.
    """

    return (page - 1) * PRODUCT_SEARCH_PAGE_SIZE + index + 1


def candidate_data(
    record: ProductSuggestionSearchRecord | ProductSuggestionListingRecord,
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


def create_selection_id(record: SelectionRecord) -> str:
    """Bind a selector to the candidate without granting access by itself."""

    return f"candidate-{record.suggestion_id}-{selection_fingerprint(record)}"


def parse_selection_token(selection_id: str) -> tuple[int, str | None]:
    """Parse a fingerprinted selector or a legacy decimal reference."""

    try:
        normalized = selection_id.strip()
    except AttributeError, TypeError:
        raise ValueError("Referência de seleção inválida") from None

    if normalized.startswith("candidate-"):
        parts = normalized.split("-")
        if len(parts) not in {2, 3}:
            raise ValueError("Referência de seleção inválida")
        normalized_id = parts[1]
        fingerprint = parts[2] if len(parts) == 3 else None  # noqa: PLR2004
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


def workflow_evidence(evidence_id: str, payload: dict[str, Any]) -> ToolEvidence:
    """Repeat the public tool data as the only evidence content."""

    return ToolEvidence(
        evidence_id=evidence_id,
        source_type="product_workflow",
        source_id=evidence_id,
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        metadata={},
    )


def evidence_key(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def tool_metadata(tool_name: str, context: ProductWorkflowContext) -> ToolMetadata:
    return create_tool_metadata(
        tool_name=tool_name,
        tool_version="1.0.0",
        tool_call_id=f"{context.request_id}:{tool_name}",
        trace_id=context.trace_id,
    )


_ResultT = TypeVar("_ResultT")


def emit_result(
    result: ToolResult[_ResultT],
    on_result: OnToolResult | None,
) -> str:
    payload = result.model_dump(mode="json")
    if on_result is not None:
        on_result(payload)
    return serialize_for_agent(result)


def failure_result(
    *,
    tool_name: str,
    context: ProductWorkflowContext,
    error: Exception,
) -> ToolResult[None]:
    category: ToolErrorCategory
    if type(error).__name__ == "ProductWorkflowDependencyError":
        category = "dependency"
        code = "PRODUCT_WORKFLOW_UNAVAILABLE"
        message = (
            "Desculpe, não foi possível consultar essas informações agora. "
            "Tente novamente mais tarde."
        )
        retryable = True
    elif isinstance(error, PermissionError):
        category = "authorization"
        code = "PRODUCT_WORKFLOW_FORBIDDEN"
        message = "Cargo sem acesso à consulta de sugestões."
        retryable = False
    elif isinstance(error, ValueError):
        category = "validation"
        code = "PRODUCT_WORKFLOW_INVALID_INPUT"
        message = "A consulta de sugestões é inválida."
        retryable = False
    else:
        category = "internal"
        code = "PRODUCT_WORKFLOW_INTERNAL"
        message = (
            "Desculpe, não foi possível consultar essas informações agora. "
            "Tente novamente mais tarde."
        )
        retryable = False
    return tool_error(
        error=create_tool_error(
            code=code,
            category=category,
            message=message,
            retryable=retryable,
        ),
        meta=tool_metadata(tool_name, context),
    )


def domain_error_result(
    *,
    tool_name: str,
    context: ProductWorkflowContext,
    code: str,
    category: ToolErrorCategory,
    message: str,
) -> ToolResult[None]:
    return tool_error(
        error=create_tool_error(
            code=code,
            category=category,
            message=message,
            retryable=False,
        ),
        meta=tool_metadata(tool_name, context),
    )
