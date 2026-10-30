"""Restore an ended conversation from MongoDB when the app requests resumption."""

from datetime import UTC, datetime
from typing import Protocol

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from .mongo_repository import MongoConversationRepository
from .summary_lock_repository import (
    ConversationSummaryLease,
    MongoConversationSummaryLockRepository,
)


class ResumableSummaryIndexer(Protocol):
    def mark_active(self, conversation_id: str) -> dict[str, object] | None: ...

    def restore_ended(self, conversation_id: str) -> bool: ...


class ConversationContextEnricher:
    """Reopen an owned conversation and map its stored history to graph messages."""

    def __init__(
        self,
        repository: MongoConversationRepository,
        *,
        summary_indexer: ResumableSummaryIndexer | None = None,
        conversation_locks: MongoConversationSummaryLockRepository | None = None,
        owner: str = "api-resume",
        lease_seconds: int = 300,
    ) -> None:
        self._repository = repository
        self._summary_indexer = summary_indexer
        self._conversation_locks = conversation_locks
        self._owner = owner
        self._lease_seconds = lease_seconds

    def restore_messages(
        self,
        *,
        email: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        now = datetime.now(UTC)
        lease: ConversationSummaryLease | None = None
        previous_point: dict[str, object] | None = None
        if self._conversation_locks is not None:
            lease = self._conversation_locks.acquire(
                conversation_id=conversation_id,
                owner=self._owner,
                now=now,
                lease_seconds=self._lease_seconds,
            )
            if lease is None:
                raise RuntimeError("conversation_resume_lock_busy")
        try:
            validate = getattr(self._repository, "validate_resume_conversation", None)
            if callable(validate):
                validate(
                    conversation_id=conversation_id,
                    email=email,
                )
            if self._summary_indexer is not None:
                previous_point = self._summary_indexer.mark_active(conversation_id)
            stored_messages = self._repository.resume_conversation(
                conversation_id=conversation_id,
                email=email,
                resumed_at=now,
            )
        except Exception:
            if previous_point is not None and previous_point.get("status") == "ended":
                try:
                    self._summary_indexer.restore_ended(conversation_id)  # type: ignore[union-attr]
                except Exception:
                    # Reconciliation will repair the cross-store state.
                    pass
            raise
        finally:
            if lease is not None and self._conversation_locks is not None:
                self._conversation_locks.release(lease=lease, now=datetime.now(UTC))
        graph_messages: list[AnyMessage] = []
        for message in stored_messages:
            message_type = HumanMessage if message.role == "user" else AIMessage
            additional_kwargs: dict[str, object] = {
                "created_at": message.created_at.isoformat(),
            }
            if message.consulted_agents is not None:
                additional_kwargs["consulted_agents"] = message.consulted_agents
            graph_messages.append(
                message_type(
                    id=message.message_id,
                    content=message.content,
                    additional_kwargs=additional_kwargs,
                )
            )
        return graph_messages
