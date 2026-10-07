from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductWorkflowContext(BaseModel):
    """Authenticated context supplied by the API, never by the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str = Field(min_length=1)
    role_id: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)


class ProductSuggestionSearchRecord(BaseModel):
    """Internal projection used to build the numbered search response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suggestion_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    store_id: int = Field(ge=1)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    store_name: str = Field(min_length=1, max_length=150)
    suggestion_type: Literal["ORDER", "PROMOTION"]
    suggestion_status: Literal[
        "GENERATED",
        "IN_EMPLOYEE_TRIAGE",
        "SENT_TO_MANAGER",
        "APPROVED",
        "REJECTED",
    ]


class ProductSuggestionCandidate(BaseModel):
    """Safe candidate shown before the user chooses a suggestion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    position: int = Field(ge=1)
    selection_ref: str = Field(min_length=1, max_length=240)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    store_name: str = Field(min_length=1, max_length=150)
    suggestion_type: Literal["ORDER", "PROMOTION"]
    suggestion_status: Literal[
        "GENERATED",
        "IN_EMPLOYEE_TRIAGE",
        "SENT_TO_MANAGER",
        "APPROVED",
        "REJECTED",
    ]


class ProductSuggestionSearchData(BaseModel):
    """Tool data for the always-numbered product search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_query: str = Field(min_length=1, max_length=200)
    outcome: Literal["found", "ambiguous", "not_found"]
    candidates: list[ProductSuggestionCandidate] = Field(max_length=6)


class SuggestionCardData(BaseModel):
    """Card fields shared by employee and manager responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selection_ref: str = Field(min_length=1, max_length=240)
    product_id: int = Field(ge=1)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    store_id: int = Field(ge=1)
    store_name: str = Field(min_length=1, max_length=150)
    suggestion_id: int = Field(ge=1)
    suggestion_type: Literal["ORDER", "PROMOTION"]
    origin: Literal["ML", "EMPLOYEE", "MANAGER"]
    status: Literal[
        "GENERATED",
        "IN_EMPLOYEE_TRIAGE",
        "SENT_TO_MANAGER",
        "APPROVED",
        "REJECTED",
    ]
    ml_batch_count: int | None = Field(default=None, gt=0)
    current_batch_count: int | None = Field(default=None, gt=0)
    effective_batch_count: int | None = Field(default=None, gt=0)
    ml_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    current_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    effective_discount_percentage: float | None = Field(default=None, ge=0, le=100)
    reference_sale_price: float | None = Field(default=None, ge=0)
    promotional_price: float | None = Field(default=None, ge=0)
    promotion_valid_from: date | None = None
    promotion_valid_until: date | None = None
    physical_expiration_date: date | None = None
    available_for_triage: bool
    created_at: datetime
    updated_at: datetime | None = None


class SuggestionTriageData(BaseModel):
    """Business triage data visible to a manager."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    employee_id: int | None = Field(default=None, ge=1)
    employee_name: str | None = Field(default=None, max_length=150)
    last_action: Literal["EDIT", "FORWARD"]
    forwarded_at: datetime | None = None
    updated_at: datetime


class ProductSuggestionDetailRecord(BaseModel):
    """Authorized database projection used to build the role-specific card."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suggestion_id: int = Field(ge=1)
    product_id: int = Field(ge=1)
    store_id: int = Field(ge=1)
    product_name: str = Field(min_length=1, max_length=200)
    category_name: str | None = Field(default=None, max_length=150)
    sku: str = Field(min_length=1, max_length=100)
    store_name: str = Field(min_length=1, max_length=150)
    suggestion_type: Literal["ORDER", "PROMOTION"]
    origin: Literal["ML", "EMPLOYEE", "MANAGER"]
    status: Literal[
        "GENERATED",
        "IN_EMPLOYEE_TRIAGE",
        "SENT_TO_MANAGER",
        "APPROVED",
        "REJECTED",
    ]
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


class SuggestionDetailData(BaseModel):
    """Role-projected detail returned by the second tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    visibility: Literal["employee", "manager"]
    card: SuggestionCardData
    triage: SuggestionTriageData | None = None
