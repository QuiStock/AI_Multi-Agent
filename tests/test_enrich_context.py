from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from src.memory.contracts import StoredMessage
from src.memory.enrich_context import ConversationContextEnricher


class FakeConversationRepository:
    def __init__(self) -> None:
        self.arguments: dict[str, Any] | None = None

    def resume_conversation(
        self,
        *,
        conversation_id: str,
        user_id: str,
        resumed_at: datetime,
    ) -> list[StoredMessage]:
        self.arguments = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "resumed_at": resumed_at,
        }
        return [
            StoredMessage(
                message_id="message-1",
                role="user",
                content="Earlier question.",
                created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
            ),
            StoredMessage(
                message_id="message-2",
                role="assistant",
                content="Earlier answer.",
                created_at=datetime(2026, 9, 20, 0, 1, tzinfo=timezone.utc),
            ),
        ]


def test_context_enricher_reopens_and_preserves_stored_message_ids() -> None:
    repository = FakeConversationRepository()
    enricher = ConversationContextEnricher(repository)  # type: ignore[arg-type]

    messages = enricher.restore_messages(
        user_id="user-1",
        conversation_id="conversation-1",
    )

    assert repository.arguments is not None
    assert repository.arguments["user_id"] == "user-1"
    assert repository.arguments["conversation_id"] == "conversation-1"
    assert repository.arguments["resumed_at"].tzinfo == timezone.utc
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)
    assert [message.id for message in messages] == ["message-1", "message-2"]
