"""Application service for persisting conversation messages."""

from datetime import datetime, timezone
from typing import Literal

from .contracts import ConversationRepository, ConversationTurn, StoredMessage


class MemoryMessageService:
    """Persist sanitized user input and final assistant responses."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def save_turn(  # noqa: PLR0913 - one persistence operation needs both messages
        self,
        *,
        conversation_id: str,
        email: str,
        request_id: str,
        sanitized_user_content: str,
        assistant_content: str,
        consulted_agents: list[str],
        sent_at: datetime | None = None,
    ) -> None:
        """Persist both ordered messages of one completed turn atomically."""
        self._validate_identifiers(conversation_id, email, request_id)
        turn = ConversationTurn(
            user_message=self._build_message(
                request_id=request_id,
                role="user",
                content=sanitized_user_content,
                created_at=sent_at,
            ),
            assistant_message=self._build_message(
                request_id=request_id,
                role="assistant",
                content=assistant_content,
                consulted_agents=consulted_agents,
            ),
        )
        self._repository.append_turn(
            conversation_id=conversation_id,
            email=email,
            turn=turn,
        )

    @staticmethod
    def _validate_identifiers(
        conversation_id: str,
        email: str,
        request_id: str,
    ) -> None:
        if not conversation_id.strip() or not email.strip() or not request_id.strip():
            raise ValueError("conversation_id, email e request_id são obrigatórios")

    @staticmethod
    def _build_message(
        *,
        request_id: str,
        role: Literal["user", "assistant"],
        content: str,
        created_at: datetime | None = None,
        consulted_agents: list[str] | None = None,
    ) -> StoredMessage:
        if not content.strip():
            raise ValueError("content não pode estar vazio")

        return StoredMessage(
            message_id=f"{request_id}:{role}",
            role=role,
            content=content,
            created_at=created_at or datetime.now(timezone.utc),
            consulted_agents=consulted_agents,
        )
