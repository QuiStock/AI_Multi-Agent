"""Incremental conversation summarization and vector-index refresh."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from src import config
from src.llm_factory import get_structured_model
from src.observability.ai_usage import invoke_with_usage
from src.observability.ai_usage_repository import (
    MongoAIUsageRepository,
    bind_usage_conversation,
)

from ..contracts import ConversationSummarySnapshot, StoredMessage
from ..mongo_repository import MongoConversationRepository
from .summary_prompt import SUMMARY_SYSTEM_PROMPT
from .title_generator import LLMConversationTitleGenerator, TitleGenerator

logger = logging.getLogger(__name__)


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

    def get(self, conversation_id: str) -> dict[str, object] | None: ...


class SummaryBoundaryNotFoundError(ValueError):
    """The persisted summary marker no longer exists in the conversation."""


class InvalidSummaryStateError(ValueError):
    """The persisted summary and its message boundary are inconsistent."""


class LLMSummaryUpdater:
    """Use the application LLM to create or incrementally update a summary."""

    def __init__(
        self,
        model: Any | None = None,
        *,
        usage_repository: MongoAIUsageRepository | None = None,
    ) -> None:
        self._model = get_structured_model(SummaryText) if model is None else model
        self._usage_repository = usage_repository

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
        result = invoke_with_usage(
            self._model,
            [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(request, ensure_ascii=False)),
            ],
            repository=self._usage_repository,
            source="summary_generation",
            model_name=config.OPENAI_MODEL,
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
        title_generator: TitleGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._summary_updater = summary_updater
        self._summary_indexer = summary_indexer
        self._title_generator = (
            LLMConversationTitleGenerator()
            if title_generator is None
            else title_generator
        )

    def run(
        self,
        *,
        email: str,
        conversation_id: str,
        before_upsert: Callable[[], None] | None = None,
    ) -> ConversationSummarySnapshot:
        with bind_usage_conversation(conversation_id):
            return self._run_with_usage_context(
                email=email,
                conversation_id=conversation_id,
                before_upsert=before_upsert,
            )

    def _run_with_usage_context(
        self,
        *,
        email: str,
        conversation_id: str,
        before_upsert: Callable[[], None] | None,
    ) -> ConversationSummarySnapshot:
        point = self._summary_indexer.get(conversation_id)
        previous_summary = point.get("summary") if point else None
        if not isinstance(previous_summary, str) or not previous_summary.strip():
            previous_summary = None
        previous_version = point.get("summary_version", 0) if point else 0
        if not isinstance(previous_version, int) or isinstance(previous_version, bool):
            previous_version = 0
        previous_marker = point.get("summarized_through_message_id") if point else None
        snapshot = self._repository.get_summary_snapshot(
            conversation_id=conversation_id,
            email=email,
            summary=previous_summary,
            summary_version=previous_version,
            summarized_through_message_id=(
                previous_marker if isinstance(previous_marker, str) else None
            ),
        )
        new_messages = self._messages_after_summary_marker(snapshot)

        if new_messages:
            updated_summary = self._summary_updater.update(
                previous_summary=snapshot.summary,
                messages=new_messages,
            )
            if not updated_summary.strip():
                raise ValueError("O resumo gerado não pode estar vazio")

            snapshot = self._repository.get_summary_snapshot(
                conversation_id=conversation_id,
                email=email,
                summary=updated_summary,
                summary_version=snapshot.summary_version + 1,
                summarized_through_message_id=new_messages[-1].message_id,
            )
        elif snapshot.summary is None:
            raise InvalidSummaryStateError(
                "A conversa não tem mensagens novas nem resumo anterior"
            )

        snapshot = self._generate_missing_title(snapshot)
        if before_upsert is not None:
            before_upsert()
        self._summary_indexer.upsert(snapshot)
        return snapshot

    def _generate_missing_title(
        self,
        snapshot: ConversationSummarySnapshot,
    ) -> ConversationSummarySnapshot:
        if snapshot.title is not None or snapshot.summary is None:
            return snapshot

        try:
            title = self._title_generator.generate(summary=snapshot.summary)
        except Exception:
            logger.warning("Falha ao gerar título; o resumo será indexado sem título.")
            return snapshot

        if not title.strip():
            logger.warning("Título vazio; o resumo será indexado sem título.")
            return snapshot

        self._repository.save_title_if_missing(
            conversation_id=snapshot.conversation_id,
            email=snapshot.email,
            title=title,
        )
        return self._repository.get_summary_snapshot(
            conversation_id=snapshot.conversation_id,
            email=snapshot.email,
            summary=snapshot.summary,
            summary_version=snapshot.summary_version,
            summarized_through_message_id=snapshot.summarized_through_message_id,
        )

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
