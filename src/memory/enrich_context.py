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
            additional_kwargs: dict[str, object] = {
                "created_at": message.created_at.isoformat(),
            }
            if message.consulted_agents is not None:
                additional_kwargs["consulted_agents"] = message.consulted_agents
            graph_messages.append(
                message_type(
                    id=message.message_id,
                    content=message.content,
                    additional_kwargs=additional_kwargs,
                )
            )
        return graph_messages
