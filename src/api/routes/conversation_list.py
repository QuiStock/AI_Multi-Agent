from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.controllers.conversation_list_controller import ConversationListController
from src.api.dependencies import get_conversation_list_controller
from src.api.schemas.conversation_list import ConversationListResponse

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/ended", response_model=ConversationListResponse)
def list_ended_conversations(
    user_id: Annotated[str, Query(min_length=1)],
    controller: Annotated[
        ConversationListController,
        Depends(get_conversation_list_controller),
    ],
) -> ConversationListResponse:
    return controller.list_ended(user_id=user_id)
