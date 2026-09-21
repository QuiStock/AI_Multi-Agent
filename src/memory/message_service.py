"""Application service for persisting conversation messages."""

from datetime import datetime, timezone
from typing import Literal

from .contracts import ConversationRepository, StoredMessage


class MemoryMessageService:
    """Persist sanitized user input and final assistant responses."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def save_user_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        request_id: str,
        sanitized_content: str,
    ) -> bool:
        """Persist input after the input guardrail has produced its safe text."""
        self._validate_identifiers(conversation_id, user_id, request_id)
        message = self._build_message(
            request_id=request_id,
            role="user",
            content=sanitized_content,
        )
        return self._persist(
            conversation_id=conversation_id,
            user_id=user_id,
            message=message,
        )

    def save_assistant_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        request_id: str,
        content: str,
        consulted_agents: list[str],
    ) -> bool:
        """Persist the final response, not intermediate agent/tool messages."""
        self._validate_identifiers(conversation_id, user_id, request_id)
        message = self._build_message(
            request_id=request_id,
            role="assistant",
            content=content,
            consulted_agents=consulted_agents,
        )
        return self._persist(
            conversation_id=conversation_id,
            user_id=user_id,
            message=message,
        )

    @staticmethod
    def _validate_identifiers(
        conversation_id: str,
        user_id: str,
        request_id: str,
    ) -> None:
        if not conversation_id.strip() or not user_id.strip() or not request_id.strip():
            raise ValueError("conversation_id, user_id e request_id são obrigatórios")

    @staticmethod
    def _build_message(
        *,
        request_id: str,
        role: Literal["user", "assistant"],
        content: str,
        consulted_agents: list[str] | None = None,
    ) -> StoredMessage:
        if not content.strip():
            raise ValueError("content não pode estar vazio")

        return StoredMessage(
            message_id=f"{request_id}:{role}",
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc),
            consulted_agents=consulted_agents,
        )

    def _persist(
        self,
        *,
        conversation_id: str,
        user_id: str,
        message: StoredMessage,
    ) -> bool:
        return self._repository.append_message(
            conversation_id=conversation_id,
            user_id=user_id,
            message=message,
        )
