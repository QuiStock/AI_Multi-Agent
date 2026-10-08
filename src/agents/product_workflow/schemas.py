"""Deprecated product-card models retained for historical compatibility tests.

The active Product Workflow contract is defined in ``models.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductCard(BaseModel):
    """Fields available on a suggestion card; client snapshots remain unverified."""

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


class ProductLookupCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str
    product_name: str
    category_name: str | None = None
    sku: str | None = None


class ProductLookupData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: Literal["found", "ambiguous", "not_found"]
    cards: list[ProductCard] = Field(default_factory=list)
    candidates: list[ProductLookupCandidate] = Field(default_factory=list)
