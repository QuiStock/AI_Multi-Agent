from __future__ import annotations

from src.api.schemas.conversation_list import (
    ConversationListItemResponse,
    ConversationListResponse,
)
from src.memory.mongo_repository import MongoConversationRepository


class ConversationListValidationError(ValueError):
    """Raised when the list query has no usable user identifier."""


class ConversationListService:
    def __init__(self, repository: MongoConversationRepository) -> None:
        self._repository = repository

    def list_ended(self, *, user_id: str) -> ConversationListResponse:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ConversationListValidationError("user_id é obrigatório")

        conversations = self._repository.list_ended_conversations(
            user_id=normalized_user_id,
        )
        return ConversationListResponse(
            conversations=[
                ConversationListItemResponse.model_validate(conversation)
                for conversation in conversations
            ]
        )
