"""Durable metadata and queue contracts for conversation summary jobs."""

from datetime import datetime
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field

SummaryJobStatus = Literal["queued", "processing", "completed", "failed"]


class SummaryJobDocument(TypedDict):
    """Persisted metadata for one asynchronous summary operation."""

    _id: str
    conversation_id: str
    user_id: str
    closure_key: str
    request_id: str
    job_type: Literal["conversation_summary"]
    status: SummaryJobStatus
    attempts: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    publication_claimed: bool
    last_error: str | None


class SummaryJob(BaseModel):
    """Validated job payload shared by MongoDB, Redis and the worker."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    closure_key: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    status: SummaryJobStatus
    attempts: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    publication_claimed: bool = False
    last_error: str | None = None


class SummaryJobRepository(Protocol):
    """Persistence boundary for job metadata outside conversations."""

    def create_or_get(  # noqa: PLR0913 - job identity is explicit
        self,
        *,
        job_id: str,
        conversation_id: str,
        user_id: str,
        closure_key: str,
        request_id: str,
        created_at: datetime,
    ) -> tuple[SummaryJob, bool]:
        """Return the job and whether this call created it."""
        ...

    def mark_published(self, *, job_id: str, published_at: datetime) -> None: ...

    def claim_publication(self, *, job_id: str, updated_at: datetime) -> bool: ...

    def release_publication(self, *, job_id: str, updated_at: datetime) -> None: ...

    def list_unpublished(self, *, limit: int = 100) -> list[SummaryJob]: ...

    def mark_processing(self, *, job_id: str, updated_at: datetime) -> bool: ...

    def mark_completed(self, *, job_id: str, updated_at: datetime) -> None: ...

    def mark_failed(
        self,
        *,
        job_id: str,
        updated_at: datetime,
        error: str,
        max_attempts: int,
    ) -> SummaryJobStatus: ...
