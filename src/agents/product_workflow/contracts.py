"""Boundaries of Product Workflow outside the tools.

The client card and the executor response cross the HTTP and graph edges.
The context and suggestion records are the repository contract.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from src.agents.schemas.tool_call import ToolCalled

SuggestionLookupStatus = Literal[
    "unique",
    "ambiguous",
    "not_found",
    "unavailable",
]
SuggestionType = Literal["ORDER", "PROMOTION"]
SuggestionStatus = Literal[
    "GENERATED",
    "IN_EMPLOYEE_TRIAGE",
    "SENT_TO_MANAGER",
    "APPROVED",
    "REJECTED",
]


class ProductCard(BaseModel):
    """Suggestion card sent by the client with a conversation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: int | None = None
    suggestion_id: int | None = None
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, max_length=100)
    suggestion_type: str | None = Field(default=None, max_length=40)
    batch_count: int | None = Field(default=None, ge=0)
    expiration_date: date | None = None
    discount_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    reference_sale_price: Decimal | None = Field(default=None, ge=0)
    promotional_price: Decimal | None = Field(default=None, ge=0)
    promotion_valid_from: date | None = None
    promotion_valid_until: date | None = None


class ProductWorkflowResponse(TypedDict):
    status: Literal["success", "error"]
    answer: str
    tools_called: NotRequired[list[ToolCalled[dict[str, Any]]]]
    error_code: NotRequired[str]


class ProductWorkflowContext(BaseModel):
    """Authenticated context supplied by the API, never by the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str = Field(min_length=1)
    user_id: int | None = Field(default=None, ge=1)
    role_code: Literal["MANAGER", "EMPLOYEE"]
    store_ids: tuple[int, ...] = Field(default_factory=tuple)
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)


class ProductSuggestionSearchRecord(BaseModel):
    """Narrow repository projection for a product-name/SKU search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suggestion_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    suggestion_type: SuggestionType
    suggestion_status: SuggestionStatus


class ProductSuggestionListingRecord(BaseModel):
    """Repository projection used by the paginated list and expiration tools."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suggestion_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    store_id: int = Field(ge=1)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    store_name: str = Field(min_length=1, max_length=150)
    suggestion_type: SuggestionType
    suggestion_status: SuggestionStatus
    promotion_valid_until: date | None = None


class ProductSuggestionDetailRecord(BaseModel):
    """Authorized database row used to build the public suggestion card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suggestion_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    store_id: int = Field(ge=1)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    store_name: str = Field(min_length=1, max_length=150)
    suggestion_type: SuggestionType
    origin: Literal["ML", "EMPLOYEE", "MANAGER"]
    status: SuggestionStatus
    ml_batch_count: int | None = Field(default=None, gt=0)
    current_batch_count: int | None = Field(default=None, gt=0)
    ml_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    current_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    reference_sale_price: float | None = Field(default=None, ge=0)
    promotional_price: float | None = Field(default=None, ge=0)
    promotion_valid_from: date | None = None
    promotion_valid_until: date | None = None
    physical_expiration_date: date | None = None
    available_for_triage: bool
    created_at: datetime
    updated_at: datetime | None = None
    employee_id: int | None = Field(default=None, ge=1)
    employee_name: str | None = Field(default=None, max_length=150)
    last_action: Literal["EDIT", "FORWARD"] | None = None
    forwarded_at: datetime | None = None
    triage_updated_at: datetime | None = None
