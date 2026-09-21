"""Contracts for durable conversational message persistence."""

from datetime import datetime
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StoredMessage(BaseModel):
    """A user message or final assistant response stored in MongoDB."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    created_at: datetime
    consulted_agents: list[str] | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at precisa incluir timezone")
        return value

    @model_validator(mode="after")
    def validate_consulted_agents(self) -> "StoredMessage":
        if self.role == "user" and self.consulted_agents is not None:
            raise ValueError("consulted_agents só pode existir em mensagens assistant")
        return self


class ConversationDocument(TypedDict):
    """Initial persisted shape for a conversation document."""

    _id: str
    user_id: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    status: Literal["active", "ended"]
    title: str | None
    summary: str | None
    summary_version: int
    summarized_through_message_id: str | None
    messages: list[dict[str, object]]
    total_turns: int


class ConversationSummarySnapshot(BaseModel):
    """MongoDB fields needed for an incremental summary update."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    title: str | None = None
    status: Literal["active", "ended"]
    summary: str | None = None
    summary_version: int = Field(ge=0)
    summarized_through_message_id: str | None = None
    messages: list[StoredMessage]
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_updated_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at precisa incluir timezone")
        return value


class ConversationSummary(TypedDict):
    """Summary fields shared by MongoDB, Qdrant, and graph memory context."""

    conversation_id: str
    title: str | None
    summary: str
    updated_at: str


class VersionedConversationSummary(ConversationSummary):
    """Authoritative MongoDB summary and version for a Qdrant candidate."""

    summary_version: int


class ConversationListItem(TypedDict):
    """Conversation fields needed by the API session list."""

    conversation_id: str
    title: str | None
    updated_at: str


class SummaryCandidate(ConversationSummary):
    """Qdrant result fields needed to validate and rank a summary."""

    summary_version: int
    score: float


class SummaryContextSelection(TypedDict):
    """Distinguish semantic matches from the agreed recent-summary fallback."""

    source: Literal["semantic", "fallback"]
    results: list[ConversationSummary]


class ConversationRepository(Protocol):
    """Persistence interface consumed by the message service."""

    def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        message: StoredMessage,
    ) -> bool:
        """Return True if inserted, or False if this message was already stored."""
        ...
