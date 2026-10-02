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

    def list_ended(self, *, email: str) -> ConversationListResponse:
        normalized_email = email.strip()
        if not normalized_email:
            raise ConversationListValidationError("email é obrigatório")

        conversations = self._repository.list_ended_conversations(
            email=normalized_email,
        )
        return ConversationListResponse(
            conversations=[
                ConversationListItemResponse.model_validate(conversation)
                for conversation in conversations
            ]
        )
