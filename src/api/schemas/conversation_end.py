from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id não pode estar vazio")
        return value


class ConversationEndResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    job_id: str
    status: Literal["ended"]
    summary_status: Literal["queued"]
