from __future__ import annotations

from src.api.schemas.conversation_delete import ConversationDeleteResponse
from src.api.services.conversation_delete_service import ConversationDeleteService


class ConversationDeleteController:
    def __init__(self, service: ConversationDeleteService) -> None:
        self._service = service

    def delete(
        self,
        *,
        conversation_id: str,
        email: str,
    ) -> ConversationDeleteResponse:
        return self._service.delete(
            conversation_id=conversation_id,
            email=email,
        )
