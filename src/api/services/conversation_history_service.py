from __future__ import annotations

from pymongo.errors import PyMongoError

from src.api.schemas.conversation_history import (
    ConversationHistoryMessageResponse,
    ConversationHistoryResponse,
)
from src.memory.mongo_repository import MongoConversationRepository


class ConversationHistoryUnavailableError(RuntimeError):
    """Raised when MongoDB cannot provide a conversation transcript."""


class ConversationHistoryService:
    def __init__(self, repository: MongoConversationRepository) -> None:
        self._repository = repository

    def get_history(
        self, *, conversation_id: str, email: str
    ) -> ConversationHistoryResponse:
        try:
            history = self._repository.get_history(
                conversation_id=conversation_id,
                email=email,
            )
        except PyMongoError as exc:
            raise ConversationHistoryUnavailableError from exc

        return ConversationHistoryResponse(
            conversation_id=history.conversation_id,
            title=history.title,
            status=history.status,
            messages=[
                ConversationHistoryMessageResponse(
                    message_id=message.message_id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at,
                )
                for message in history.messages
            ],
        )
