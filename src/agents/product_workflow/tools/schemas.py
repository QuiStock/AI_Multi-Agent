"""Deprecated arguments for the historical product-card tool."""

from pydantic import BaseModel, ConfigDict, Field


class ProductCardLookupArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_query: str = Field(min_length=1, max_length=200)
