from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.controllers.conversation_list_controller import ConversationListController
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_list_controller,
)
from src.api.schemas.conversation_list import ConversationListResponse
from src.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/ended", response_model=ConversationListResponse)
def list_ended_conversations(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    controller: Annotated[
        ConversationListController,
        Depends(get_conversation_list_controller),
    ],
) -> ConversationListResponse:
    return controller.list_ended(email=principal.email)
