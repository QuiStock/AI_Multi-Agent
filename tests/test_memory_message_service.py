from datetime import datetime, timezone

import pytest

from src.memory.contracts import StoredMessage
from src.memory.message_service import MemoryMessageService


class RecordingRepository:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, StoredMessage]] = []

    def append_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        message: StoredMessage,
    ) -> bool:
        self.messages.append((conversation_id, user_id, message))
        return True


def test_user_message_is_saved_with_stable_id_and_user_role() -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)

    inserted = service.save_user_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_content="  Guardrail-approved message  ",
    )

    assert inserted is True
    conversation_id, user_id, message = repository.messages[0]
    assert conversation_id == "conversation-1"
    assert user_id == "user-1"
    assert message.message_id == "request-1:user"
    assert message.role == "user"
    assert message.content == "  Guardrail-approved message  "
    assert message.consulted_agents is None
    assert message.created_at.tzinfo == timezone.utc


def test_assistant_message_stores_consulted_agents() -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)

    service.save_assistant_message(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        content="Final response",
        consulted_agents=["product_workflow"],
    )

    message = repository.messages[0][2]
    assert message.message_id == "request-1:assistant"
    assert message.role == "assistant"
    assert message.consulted_agents == ["product_workflow"]


def test_save_turn_uses_sent_at_for_the_user_message() -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)
    sent_at = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)

    service.save_turn(
        conversation_id="conversation-1",
        user_id="user-1",
        request_id="request-1",
        sanitized_user_content="Pergunta sanitizada",
        assistant_content="Resposta final",
        consulted_agents=["faq"],
        sent_at=sent_at,
    )

    assert repository.messages[0][2].created_at == sent_at
    assert repository.messages[1][2].role == "assistant"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conversation_id", " "),
        ("user_id", " "),
        ("request_id", " "),
    ],
)
def test_user_message_requires_identifiers(field: str, value: str) -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)
    identifiers = {
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "request_id": "request-1",
    }
    identifiers[field] = value

    with pytest.raises(ValueError, match="obrigatórios"):
        service.save_user_message(
            **identifiers,
            sanitized_content="Hello",
        )

    assert repository.messages == []


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
def test_user_message_rejects_blank_content(content: str) -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)

    with pytest.raises(ValueError, match="content"):
        service.save_user_message(
            conversation_id="conversation-1",
            user_id="user-1",
            request_id="request-1",
            sanitized_content=content,
        )

    assert repository.messages == []


def test_stored_message_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone"):
        StoredMessage(
            message_id="message-1",
            role="user",
            content="Hello",
            created_at=datetime(2026, 9, 20),
        )


def test_user_message_cannot_contain_agent_metadata() -> None:
    with pytest.raises(ValueError, match="consulted_agents"):
        StoredMessage(
            message_id="message-1",
            role="user",
            content="Hello",
            created_at=datetime.now(timezone.utc),
            consulted_agents=[],
        )
