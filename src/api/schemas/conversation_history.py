from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ConversationHistoryMessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    role: Literal["user", "assistant"]
    content: str
    created_at: AwareDatetime


class ConversationHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    title: str | None
    status: Literal["active", "ended"]
    messages: list[ConversationHistoryMessageResponse]
