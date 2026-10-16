"""Structured result schemas for conversational-summary search."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmptySearchArguments(BaseModel):
    """The agent supplies no identity or query; both come from trusted state."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConversationSummaryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str = Field(min_length=1)
    title: str | None = None
    summary: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    summary_version: int | None = Field(default=None, ge=1)
    summarized_through_message_id: str | None = None


class SearchConversationSummariesData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["temporal", "semantic", "recent_fallback", "none"]
    results: list[ConversationSummaryItem] = Field(max_length=3)
