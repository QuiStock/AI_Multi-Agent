from datetime import datetime, timezone

import pytest

from src.memory.contracts import ConversationTurn, StoredMessage
from src.memory.message_service import MemoryMessageService


class RecordingRepository:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str, ConversationTurn]] = []
        self.calls = 0

    def append_turn(
        self,
        *,
        conversation_id: str,
        email: str,
        turn: ConversationTurn,
    ) -> None:
        self.calls += 1
        self.turns.append((conversation_id, email, turn))


def test_save_turn_calls_repository_once_with_two_ordered_messages() -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)
    sent_at = datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)

    service.save_turn(
        conversation_id="conversation-1",
        email="user-1",
        request_id="request-1",
        sanitized_user_content="  Guardrail-approved message  ",
        assistant_content="Final response",
        consulted_agents=["product_workflow"],
        sent_at=sent_at,
    )

    assert repository.calls == 1
    conversation_id, email, turn = repository.turns[0]
    assert (conversation_id, email) == ("conversation-1", "user-1")
    assert turn.user_message.message_id == "request-1:user"
    assert turn.user_message.role == "user"
    assert turn.user_message.content == "  Guardrail-approved message  "
    assert turn.user_message.consulted_agents is None
    assert turn.user_message.created_at == sent_at
    assert turn.assistant_message.message_id == "request-1:assistant"
    assert turn.assistant_message.role == "assistant"
    assert turn.assistant_message.content == "Final response"
    assert turn.assistant_message.consulted_agents == ["product_workflow"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conversation_id", " "),
        ("email", " "),
        ("request_id", " "),
    ],
)
def test_save_turn_requires_identifiers(field: str, value: str) -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)
    arguments = {
        "conversation_id": "conversation-1",
        "email": "user-1",
        "request_id": "request-1",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match="obrigatórios"):
        service.save_turn(
            **arguments,
            sanitized_user_content="Question",
            assistant_content="Answer",
            consulted_agents=[],
        )

    assert repository.calls == 0


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
@pytest.mark.parametrize("message", ["user", "assistant"])
def test_save_turn_rejects_blank_content(content: str, message: str) -> None:
    repository = RecordingRepository()
    service = MemoryMessageService(repository)
    values = {
        "conversation_id": "conversation-1",
        "email": "user-1",
        "request_id": "request-1",
        "sanitized_user_content": "Question",
        "assistant_content": "Answer",
        "consulted_agents": [],
    }
    values["sanitized_user_content" if message == "user" else "assistant_content"] = (
        content
    )

    with pytest.raises(ValueError, match="content"):
        service.save_turn(**values)

    assert repository.calls == 0


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


def test_turn_contract_requires_user_then_assistant_roles() -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="role=user"):
        ConversationTurn(
            user_message=StoredMessage(
                message_id="assistant-1",
                role="assistant",
                content="Wrong role",
                created_at=now,
            ),
            assistant_message=StoredMessage(
                message_id="assistant-2",
                role="assistant",
                content="Answer",
                created_at=now,
            ),
        )
