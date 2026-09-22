from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from src.api.controllers.conversation_controller import ConversationController
from src.api.dependencies import get_conversation_controller
from src.api.schemas.conversation import ConversationRequest, ConversationResponse

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "/{conversation_id}/messages",
    response_model=ConversationResponse,
)
def converse(
    conversation_id: Annotated[str, Path(min_length=1)],
    request: ConversationRequest,
    controller: Annotated[
        ConversationController,
        Depends(get_conversation_controller),
    ],
) -> ConversationResponse:
    return controller.converse(
        conversation_id=conversation_id,
        request=request,
    )
