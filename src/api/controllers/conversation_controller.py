from __future__ import annotations

from src.api.schemas.conversation import ConversationRequest, ConversationResponse
from src.api.services.conversation_service import ConversationService


class ConversationController:
    """Coordinate HTTP input and the conversation application service."""

    def __init__(self, service: ConversationService) -> None:
        self._service = service

    def converse(
        self,
        *,
        conversation_id: str,
        request: ConversationRequest,
    ) -> ConversationResponse:
        return self._service.converse(
            conversation_id=conversation_id,
            request=request,
        )
