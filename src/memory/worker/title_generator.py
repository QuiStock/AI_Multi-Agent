"""Generate a stable display title from a persisted conversation summary."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.llm_factory import get_title_model

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
    """Use the dedicated Gemini Flash-Lite structured-output model."""

    def __init__(self, model: Any | None = None) -> None:
        self._model = get_title_model(ConversationTitle) if model is None else model

    def generate(self, *, summary: str) -> str:
        if not summary.strip():
            raise ValueError("summary é obrigatório para gerar title")
        request = {"summary": summary}
        result = self._model.invoke(
            [
                SystemMessage(content=CONVERSATION_TITLE_PROMPT),
                HumanMessage(content=json.dumps(request, ensure_ascii=False)),
            ]
        )
        if not isinstance(result, ConversationTitle):
            result = ConversationTitle.model_validate(result)
        return result.title
