from __future__ import annotations

from src.api.schemas.conversation_end import ConversationEndResponse
from src.api.services.conversation_end_service import ConversationEndService


class ConversationEndController:
    def __init__(self, service: ConversationEndService) -> None:
        self._service = service

    def end(
        self,
        *,
        conversation_id: str,
        email: str,
    ) -> ConversationEndResponse:
        return self._service.end(
            conversation_id=conversation_id,
            email=email,
        )
