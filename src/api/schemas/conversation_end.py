from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConversationEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationEndResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    job_id: str
    status: Literal["ended"]
    summary_status: Literal["queued", "processing", "completed", "failed", "superseded"]
