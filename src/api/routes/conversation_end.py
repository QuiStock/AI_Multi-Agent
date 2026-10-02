from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from src.api.controllers.conversation_end_controller import ConversationEndController
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_end_controller,
)
from src.api.schemas.conversation_end import ConversationEndResponse
from src.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post(
    "/{conversation_id}/end",
    response_model=ConversationEndResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def end_conversation(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    conversation_id: Annotated[str, Path(min_length=1)],
    controller: Annotated[
        ConversationEndController,
        Depends(get_conversation_end_controller),
    ],
) -> ConversationEndResponse:
    return controller.end(
        conversation_id=conversation_id,
        email=principal.email,
    )
