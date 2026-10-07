"""Durable metadata contract for asynchronous conversation-summary jobs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SummaryJobStatus = Literal["queued", "processing", "completed", "failed", "superseded"]
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_BASE_SECONDS = 2
DEFAULT_RETRY_MAX_SECONDS = 300


class SummaryJob(BaseModel):
    """Job metadata only; transcript and generated summary are never fields here."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    closure_key: str = Field(min_length=1)
    request_id: str | None = None
    status: SummaryJobStatus = "queued"
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    next_attempt_at: datetime | None = None
    lease_owner: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None

    @field_validator(
        "created_at", "updated_at", "published_at", "next_attempt_at", "lease_until"
    )
    @classmethod
    def require_aware_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Datas do job precisam incluir timezone")
        return value


def retry_delay_seconds(
    attempts: int,
    *,
    base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
    max_seconds: int = DEFAULT_RETRY_MAX_SECONDS,
) -> int:
    """Return bounded exponential backoff for a one-based attempt count."""
    if attempts < 1:
        raise ValueError("attempts precisa ser pelo menos 1")
    if base_seconds < 1 or max_seconds < base_seconds:
        raise ValueError("Configuração de backoff inválida")
    delay = base_seconds * (1 << (attempts - 1))
    return delay if delay < max_seconds else max_seconds
