"""Generate a stable display title from a persisted conversation summary."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import config
from src.llm_factory import get_title_model
from src.observability.ai_usage import invoke_with_usage
from src.observability.ai_usage_repository import MongoAIUsageRepository

from .title_prompt import CONVERSATION_TITLE_PROMPT


class ConversationTitle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def require_nonblank_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title não pode estar vazio")
        return title


class TitleGenerator(Protocol):
    def generate(self, *, summary: str) -> str: ...


class LLMConversationTitleGenerator:
    """Use the configured OpenAI model for structured conversation titles."""

    def __init__(
        self,
        model: Any | None = None,
        *,
        usage_repository: MongoAIUsageRepository | None = None,
    ) -> None:
        self._model = get_title_model(ConversationTitle) if model is None else model
        self._usage_repository = usage_repository

    def generate(self, *, summary: str) -> str:
        if not summary.strip():
            raise ValueError("summary é obrigatório para gerar title")
        request = {"summary": summary}
        result = invoke_with_usage(
            self._model,
            [
                SystemMessage(content=CONVERSATION_TITLE_PROMPT),
                HumanMessage(content=json.dumps(request, ensure_ascii=False)),
            ],
            repository=self._usage_repository,
            source="title_generation",
            model_name=config.OPENAI_MODEL,
        )
        if not isinstance(result, ConversationTitle):
            result = ConversationTitle.model_validate(result)
        return result.title
