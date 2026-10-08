from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConversationDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    request_id: str
    job_id: str
    status: Literal["deleting"]
    cleanup_status: Literal["queued", "processing", "completed", "failed", "superseded"]
