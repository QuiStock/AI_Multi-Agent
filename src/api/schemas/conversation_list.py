from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConversationListItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    title: str | None = None
    updated_at: str = Field(min_length=1)


class ConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversations: list[ConversationListItemResponse]
