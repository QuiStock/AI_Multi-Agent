"""LangChain callback for LLM calls that do not belong to a turn trace."""

from __future__ import annotations

from collections.abc import Mapping
from inspect import Parameter, signature
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from src.observability.ai_usage_repository import (
    MongoAIUsageRepository,
    UsageSource,
    record_usage_safely,
)


class AIUsageCallbackHandler(BaseCallbackHandler):
    """Record token usage from one configured source without retaining content."""

    raise_error = False

    def __init__(
        self,
        *,
        repository: MongoAIUsageRepository | None,
        source: UsageSource,
        model: str,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._source = source
        self._model = model

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        input_tokens, output_tokens = self._token_usage(response)
        record_usage_safely(
            self._repository,
            event_id=str(run_id),
            source=self._source,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status="completed",
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        record_usage_safely(
            self._repository,
            event_id=str(run_id),
            source=self._source,
            model=self._model,
            input_tokens=None,
            output_tokens=None,
            status="error",
        )

    @classmethod
    def _token_usage(cls, response: LLMResult) -> tuple[int | None, int | None]:
        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None)
                if isinstance(usage, Mapping):
                    return (
                        cls._first_int(usage, ("input_tokens", "prompt_tokens")),
                        cls._first_int(usage, ("output_tokens", "completion_tokens")),
                    )

        llm_output = response.llm_output
        if isinstance(llm_output, Mapping):
            usage = llm_output.get("token_usage") or llm_output.get("usage")
            if isinstance(usage, Mapping):
                return (
                    cls._first_int(usage, ("input_tokens", "prompt_tokens")),
                    cls._first_int(usage, ("output_tokens", "completion_tokens")),
                )
        return None, None

    @staticmethod
    def _first_int(values: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = values.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None


def invoke_with_usage(
    model: Any,
    inputs: Any,
    *,
    repository: MongoAIUsageRepository | None,
    source: UsageSource,
    model_name: str,
) -> Any:
    """Invoke a LangChain runnable and persist its token callback metadata."""
    handler = AIUsageCallbackHandler(
        repository=repository,
        source=source,
        model=model_name,
    )
    try:
        parameters = signature(model.invoke).parameters.values()
        accepts_config = any(
            parameter.name == "config" or parameter.kind is Parameter.VAR_KEYWORD
            for parameter in parameters
        )
    except TypeError, ValueError:
        accepts_config = True
    if not accepts_config:
        return model.invoke(inputs)
    return model.invoke(inputs, config={"callbacks": [handler]})
