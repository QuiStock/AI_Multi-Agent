"""Contracts for durable conversational message persistence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_SUMMARY_RESULTS = 3


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


class ConversationTurn(BaseModel):
    """The two ordered messages written atomically for one completed turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_message: StoredMessage
    assistant_message: StoredMessage

    @model_validator(mode="after")
    def validate_turn_messages(self) -> "ConversationTurn":
        if self.user_message.role != "user":
            raise ValueError("user_message precisa ter role=user")
        if self.assistant_message.role != "assistant":
            raise ValueError("assistant_message precisa ter role=assistant")
        if self.user_message.message_id == self.assistant_message.message_id:
            raise ValueError("As mensagens do turno precisam de IDs distintos")
        return self


class ConversationDocument(TypedDict):
    """Persisted conversation shape; summary state belongs to Qdrant."""

    _id: str
    email: str
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None
    status: Literal["active", "ended", "deleting"]
    title: str | None
    messages: list[dict[str, object]]
    total_turns: int


class ConversationSummarySnapshot(BaseModel):
    """Runtime summary context assembled from Mongo messages and Qdrant point."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    email: str = Field(min_length=1)
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


class SummaryCommit(BaseModel):
    """Runtime summary revision; it must only be persisted in Qdrant."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(min_length=1)
    email: str = Field(min_length=1)
    expected_summary_version: int = Field(ge=0)
    expected_message_id: str | None
    summary: str = Field(min_length=1)
    summarized_through_message_id: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class SummarySearchRequest:
    """Inputs for one semantic summary search."""

    email: str
    conversation_id: str
    query: str
    collection_name: str
    limit: int = MAX_SUMMARY_RESULTS
    score_threshold: float = 0.5


class ConversationSummary(TypedDict):
    """Summary fields returned to graph memory context from Qdrant."""

    conversation_id: str
    title: str | None
    summary: str
    updated_at: str


class VersionedConversationSummary(ConversationSummary):
    """Summary point returned by Qdrant after Mongo ownership validation."""

    summary_version: int


class ConversationMetadata(TypedDict):
    """Mongo metadata used only to validate owner and ended status."""

    conversation_id: str
    title: str | None
    updated_at: str


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

    def append_turn(
        self,
        *,
        conversation_id: str,
        email: str,
        turn: ConversationTurn,
    ) -> None:
        """Append the user and assistant messages in one atomic Mongo update."""
        ...
