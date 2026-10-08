"""Centralized LLM and embedding instances used by the application."""

from __future__ import annotations

from typing import Any, TypeVar

from langchain_core.runnables import Runnable
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr

from src import config


def _secret(value: str | None, provider: str) -> SecretStr:
    """Keep model construction import-safe when credentials are absent."""

    return SecretStr(value or f"missing-{provider}-api-key")


llm_openai = ChatOpenAI(
    model=config.OPENAI_MODEL,
    api_key=_secret(config.OPENAI_API_KEY, "openai"),
    use_responses_api=True,
    reasoning_effort="low",
)

llm = llm_openai

embeddings = GoogleGenerativeAIEmbeddings(
    model=config.GEMINI_EMBEDDING_MODEL,
    api_key=_secret(config.GEMINI_API_KEY, "gemini"),
    output_dimensionality=768,
)


SchemaT = TypeVar("SchemaT", bound=BaseModel)


def get_structured_model(
    schema: type[SchemaT],
) -> Runnable[Any, Any]:
    """Bind a schema to the configured OpenAI chat model."""
    return llm_openai.with_structured_output(schema)


def get_title_model(schema: type[SchemaT]) -> Runnable[Any, Any]:
    """Return structured output from the configured OpenAI chat model."""
    return llm_openai.with_structured_output(schema)


def get_configured_chat_model(model_id: str) -> Runnable[Any, Any]:
    """Resolve only the chat models configured for the agent runtime."""
    if model_id == config.OPENAI_MODEL:
        return llm_openai
    raise ValueError("model_id não corresponde a um modelo de chat configurado")


__all__ = [
    "embeddings",
    "get_structured_model",
    "get_title_model",
    "get_configured_chat_model",
    "llm",
    "llm_openai",
]
