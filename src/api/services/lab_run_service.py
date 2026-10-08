from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from src import config
from src.api.schemas.observability import LabRunRequest
from src.observability.ai_usage import invoke_with_usage
from src.observability.ai_usage_repository import MongoAIUsageRepository


class UnsupportedLabModelError(ValueError):
    """Raised when a request selects a model outside the configured catalog."""


class LabModelInvocationError(RuntimeError):
    """Raised when the selected model cannot return a textual result."""


class LabRunService:
    """Invoke one configured chat model with an editable prompt and history."""

    def __init__(
        self,
        *,
        model_resolver: Callable[[str], Runnable[Any, Any]],
        usage_repository: MongoAIUsageRepository | None = None,
    ) -> None:
        self._model_resolver = model_resolver
        self._usage_repository = usage_repository

    def run(self, request: LabRunRequest) -> str:
        try:
            model = self._model_resolver(request.model_id.strip())
        except ValueError as exc:
            raise UnsupportedLabModelError from exc

        messages: list[Any] = [SystemMessage(content=request.prompt)]
        for message in request.messages:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))

        try:
            model_response = invoke_with_usage(
                model,
                messages,
                repository=self._usage_repository,
                source="lab",
                model_name=request.model_id.strip() or config.OPENAI_MODEL,
            )
        except Exception as exc:
            raise LabModelInvocationError from exc

        content = getattr(model_response, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_blocks = [
                block["text"]
                for block in content
                if isinstance(block, Mapping)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ]
            if text_blocks:
                return "".join(text_blocks)
        raise LabModelInvocationError("O modelo não retornou conteúdo textual")
