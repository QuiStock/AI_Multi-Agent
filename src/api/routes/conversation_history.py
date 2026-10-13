from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from src.api.controllers.conversation_history_controller import (
    ConversationHistoryController,
)
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_history_controller,
)
from src.api.schemas.conversation_history import ConversationHistoryResponse
from src.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/{conversation_id}/messages", response_model=ConversationHistoryResponse)
def get_conversation_history(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    conversation_id: Annotated[str, Path(min_length=1)],
    controller: Annotated[
        ConversationHistoryController,
        Depends(get_conversation_history_controller),
    ],
) -> ConversationHistoryResponse:
    return controller.get_history(
        conversation_id=conversation_id,
        email=principal.email,
    )
