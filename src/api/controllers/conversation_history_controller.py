from __future__ import annotations

from src.api.schemas.conversation_history import ConversationHistoryResponse
from src.api.services.conversation_history_service import ConversationHistoryService


class ConversationHistoryController:
    def __init__(self, service: ConversationHistoryService) -> None:
        self._service = service

    def get_history(
        self, *, conversation_id: str, email: str
    ) -> ConversationHistoryResponse:
        return self._service.get_history(conversation_id=conversation_id, email=email)
