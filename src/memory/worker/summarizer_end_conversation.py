"""Incremental conversation summarization and vector-index refresh."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from src.llm_factory import get_structured_model

from ..contracts import ConversationSummarySnapshot, StoredMessage
from ..mongo_repository import (
    MongoConversationRepository,
    SummaryUpdateConflictError,
)
from .summary_prompt import SUMMARY_SYSTEM_PROMPT


class SummaryText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)


class SummaryUpdater(Protocol):
    def update(
        self,
        *,
        previous_summary: str | None,
        messages: Sequence[StoredMessage],
    ) -> str: ...


class SummaryIndexer(Protocol):
    def upsert(self, snapshot: ConversationSummarySnapshot) -> None: ...


class SummaryBoundaryNotFoundError(ValueError):
    """The persisted summary marker no longer exists in the conversation."""


class InvalidSummaryStateError(ValueError):
    """The persisted summary and its message boundary are inconsistent."""


class LLMSummaryUpdater:
    """Use the application LLM to create or incrementally update a summary."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = get_structured_model(SummaryText) if model is None else model

    def update(
        self,
        *,
        previous_summary: str | None,
        messages: Sequence[StoredMessage],
    ) -> str:
        mode = "incremental" if previous_summary is not None else "initial"
        request = {
            "mode": mode,
            "previous_summary": previous_summary,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        result = self._model.invoke(
            [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(request, ensure_ascii=False)),
            ]
        )
        if not isinstance(result, SummaryText):
            result = SummaryText.model_validate(result)
        return result.summary.strip()


class EndConversationSummaryWorker:
    """Close a conversation, summarize only its unprocessed messages, and index."""

    def __init__(
        self,
        *,
        repository: MongoConversationRepository,
        summary_updater: SummaryUpdater,
        summary_indexer: SummaryIndexer,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._summary_updater = summary_updater
        self._summary_indexer = summary_indexer
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> ConversationSummarySnapshot:
        self._repository.mark_ended(
            conversation_id=conversation_id,
            user_id=user_id,
            ended_at=self._clock(),
        )
        snapshot = self._repository.get_summary_snapshot(
            conversation_id=conversation_id,
            user_id=user_id,
        )
        new_messages = self._messages_after_summary_marker(snapshot)

        if new_messages:
            updated_summary = self._summary_updater.update(
                previous_summary=snapshot.summary,
                messages=new_messages,
            )
            if not updated_summary.strip():
                raise ValueError("O resumo gerado não pode estar vazio")

            committed = self._repository.save_summary_if_current(
                conversation_id=conversation_id,
                user_id=user_id,
                expected_summary_version=snapshot.summary_version,
                expected_message_id=snapshot.summarized_through_message_id,
                summary=updated_summary,
                summarized_through_message_id=new_messages[-1].message_id,
            )
            if not committed:
                raise SummaryUpdateConflictError(conversation_id)

            snapshot = self._repository.get_summary_snapshot(
                conversation_id=conversation_id,
                user_id=user_id,
            )
        elif snapshot.summary is None:
            raise InvalidSummaryStateError(
                "A conversa não tem mensagens novas nem resumo anterior"
            )

        self._summary_indexer.upsert(snapshot)
        return snapshot

    @staticmethod
    def _messages_after_summary_marker(
        snapshot: ConversationSummarySnapshot,
    ) -> list[StoredMessage]:
        marker = snapshot.summarized_through_message_id
        if marker is None:
            if snapshot.summary is not None:
                raise InvalidSummaryStateError(
                    "Existe resumo sem summarized_through_message_id"
                )
            return list(snapshot.messages)

        if snapshot.summary is None:
            raise InvalidSummaryStateError(
                "Existe summarized_through_message_id sem resumo"
            )

        for index, message in enumerate(snapshot.messages):
            if message.message_id == marker:
                return list(snapshot.messages[index + 1 :])

        raise SummaryBoundaryNotFoundError(
            f"O marcador de resumo {marker!r} não está no histórico"
        )
