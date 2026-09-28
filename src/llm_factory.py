"""Centralized LLM and embedding instances used by the application."""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_groq import ChatGroq
from pydantic import BaseModel, SecretStr

from src import config


def _secret(value: str | None, provider: str) -> SecretStr:
    """Keep model construction import-safe when credentials are absent."""

    return SecretStr(value or f"missing-{provider}-api-key")


llm_gemini = ChatGoogleGenerativeAI(
    model=config.GEMINI_CHAT_MODEL,
    temperature=config.LLM_TEMPERATURE,
    top_p=config.LLM_TOP_P,
    google_api_key=config.GEMINI_API_KEY or "missing-gemini-api-key",
)

llm_gemini_title = ChatGoogleGenerativeAI(
    model=config.GEMINI_TITLE_MODEL,
    temperature=0.0,
    google_api_key=config.GEMINI_API_KEY or "missing-gemini-api-key",
)

llm_groq = ChatGroq(
    model=config.GROQ_CHAT_MODEL,
    temperature=config.LLM_TEMPERATURE,
    model_kwargs={"top_p": config.LLM_TOP_P},
    api_key=_secret(config.GROQ_API_KEY, "groq"),
)

# Temporary Gemini-only configuration for local flow testing. This prevents
# the FAQ and guardrail paths from calling the unavailable Groq model.
llm = llm_gemini

llm_fast = ChatGoogleGenerativeAI(
    model=config.GEMINI_CHAT_MODEL,
    temperature=0.0,
    google_api_key=config.GEMINI_API_KEY or "missing-gemini-api-key",
)

embeddings = GoogleGenerativeAIEmbeddings(
    model=config.GEMINI_EMBEDDING_MODEL,
    api_key=_secret(config.GEMINI_API_KEY, "gemini"),
    output_dimensionality=768,
)


SchemaT = TypeVar("SchemaT", bound=BaseModel)
StructuredModelKind = Literal["default", "fast"]


def get_structured_model(
    schema: type[SchemaT],
    *,
    kind: StructuredModelKind = "default",
) -> Runnable[Any, Any]:
    """Return a structured model with the appropriate agent model policy.

    ``RunnableWithFallbacks`` does not expose ``with_structured_output``
    directly. Therefore structured output is bound to each provider first,
    and only then is the fallback chain assembled.
    """

    if kind == "fast":
        return llm_fast.with_structured_output(schema)

    return llm_gemini.with_structured_output(schema)


def get_title_model(schema: type[SchemaT]) -> Runnable[Any, Any]:
    """Return Gemini Flash-Lite structured output for conversation titles."""
    return llm_gemini_title.with_structured_output(schema)


__all__ = [
    "embeddings",
    "get_structured_model",
    "get_title_model",
    "llm",
    "llm_fast",
    "llm_gemini",
    "llm_gemini_title",
    "llm_groq",
]
