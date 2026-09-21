"""Restore an ended conversation from MongoDB when the app requests resumption."""

from datetime import UTC, datetime

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from .mongo_repository import MongoConversationRepository


class ConversationContextEnricher:
    """Reopen an owned conversation and map its stored history to graph messages."""

    def __init__(self, repository: MongoConversationRepository) -> None:
        self._repository = repository

    def restore_messages(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> list[AnyMessage]:
        stored_messages = self._repository.resume_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            resumed_at=datetime.now(UTC),
        )
        graph_messages: list[AnyMessage] = []
        for message in stored_messages:
            message_type = HumanMessage if message.role == "user" else AIMessage
            graph_messages.append(
                message_type(
                    id=message.message_id,
                    content=message.content,
                )
            )
        return graph_messages
