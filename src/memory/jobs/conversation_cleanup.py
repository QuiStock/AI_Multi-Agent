"""Idempotent cross-store conversation cleanup."""

from __future__ import annotations

from collections.abc import Callable

from .mongo_repository import MongoConversationRepository
from .qdrant_summary_indexer import QdrantSummaryIndexer


class ConversationCleanupProcessor:
    def __init__(
        self,
        *,
        conversations: MongoConversationRepository,
        summary_indexer: QdrantSummaryIndexer,
    ) -> None:
        self._conversations = conversations
        self._summary_indexer = summary_indexer

    def delete(
        self,
        *,
        email: str,
        conversation_id: str,
        before_delete: Callable[[], None] | None = None,
    ) -> None:
        if before_delete is not None:
            before_delete()
        self._summary_indexer.delete(conversation_id)
        if before_delete is not None:
            before_delete()
        self._conversations.delete_conversation(
            conversation_id=conversation_id,
            email=email,
        )
