from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class ConversationRequest(BaseModel):
    """Input required to process one user message."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=4_000)
    sent_at: AwareDatetime
    is_resuming_conversation: bool = False

    @field_validator("user_id", "message")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("o campo não pode estar vazio")
        return value


class ConversationResponse(BaseModel):
    """Metadata and final response returned by the conversation endpoint."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    response: str
    status: Literal[
        "success",
        "rejected",
        "clarification_required",
        "out_of_scope",
        "error",
    ]
