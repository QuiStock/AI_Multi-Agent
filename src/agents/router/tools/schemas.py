"""Structured result schemas for conversational-summary search."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmptySearchArguments(BaseModel):
    """The router supplies no identity or query; both come from trusted state."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConversationSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str = Field(min_length=1)
    title: str | None = None
    summary: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)


class SearchConversationSummariesData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["semantic", "fallback"]
    results: list[ConversationSummaryItem] = Field(max_length=3)
