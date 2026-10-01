from __future__ import annotations

from src.api.schemas.conversation_list import ConversationListResponse
from src.api.services.conversation_list_service import ConversationListService


class ConversationListController:
    def __init__(self, service: ConversationListService) -> None:
        self._service = service

    def list_ended(self, *, email: str) -> ConversationListResponse:
        return self._service.list_ended(email=email)
