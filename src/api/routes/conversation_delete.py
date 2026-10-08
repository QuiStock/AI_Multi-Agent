from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from src.api.controllers.conversation_delete_controller import (
    ConversationDeleteController,
)
from src.api.dependencies import (
    get_authenticated_principal,
    get_conversation_delete_controller,
)
from src.api.schemas.conversation_delete import ConversationDeleteResponse
from src.auth.models import AuthenticatedPrincipal

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.delete(
    "/{conversation_id}",
    response_model=ConversationDeleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_conversation(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    conversation_id: Annotated[str, Path(min_length=1)],
    controller: Annotated[
        ConversationDeleteController,
        Depends(get_conversation_delete_controller),
    ],
) -> ConversationDeleteResponse:
    return controller.delete(
        conversation_id=conversation_id,
        email=principal.email,
    )
