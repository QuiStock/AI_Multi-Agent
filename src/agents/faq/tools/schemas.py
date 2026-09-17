from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FAQToolModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


class FAQSearchItem(FAQToolModel):
    file_name: str = Field(
        min_length=1,
        max_length=240,
    )

    content: str = Field(
        min_length=1,
        max_length=12_000,
    )

    relevance: float = Field(
        ge=0,
        le=1,
    )

    page: int | None = Field(
        default=None,
        ge=1,
    )


class FAQSearchData(FAQToolModel):
    query: str = Field(
        min_length=1,
        max_length=1_000,
    )

    result_count: int = Field(
        ge=0,
    )

    results: list[FAQSearchItem] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_result_count(self) -> Self:
        if self.result_count != len(self.results):
            raise ValueError(
                "result_count must match the number of results",
            )

        return self
