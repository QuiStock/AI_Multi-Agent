"""Structured result schemas for conversational-summary search."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchConversationSummariesArguments(BaseModel):
    """Optional inclusive date range; identity and query come from trusted state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start_date: date | None = Field(
        default=None,
        description="Primeiro dia inclusivo do período, no formato YYYY-MM-DD.",
    )
    end_date: date | None = Field(
        default=None,
        description="Último dia inclusivo do período, no formato YYYY-MM-DD.",
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> SearchConversationSummariesArguments:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date e end_date devem ser informados juntos")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("start_date deve ser anterior ou igual a end_date")
        return self


class ConversationSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class SearchConversationSummariesData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    results: list[ConversationSummaryItem] = Field(max_length=3)
