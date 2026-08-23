"""Centralized LLM and embedding instances used by the application."""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_groq import ChatGroq
from pydantic import BaseModel, SecretStr

from src import config


def _secret(value: str | None) -> SecretStr | None:
    return SecretStr(value) if value else None


llm_gemini = ChatGoogleGenerativeAI(
    model=config.GEMINI_CHAT_MODEL,
    temperature=config.LLM_TEMPERATURE,
    top_p=config.LLM_TOP_P,
    google_api_key=config.GEMINI_API_KEY,
)

llm_groq = ChatGroq(
    model=config.GROQ_CHAT_MODEL,
    temperature=config.LLM_TEMPERATURE,
    model_kwargs={"top_p": config.LLM_TOP_P},
    api_key=_secret(config.GROQ_API_KEY),
)

# Gemini is the primary model. Groq is used when the primary invocation fails.
llm = llm_gemini.with_fallbacks([llm_groq])

llm_fast = ChatGroq(
    model=config.GROQ_FAST_MODEL,
    temperature=0.0,
    api_key=_secret(config.GROQ_API_KEY),
)

embeddings = GoogleGenerativeAIEmbeddings(
    model=config.GEMINI_EMBEDDING_MODEL,
    api_key=_secret(config.GEMINI_API_KEY),
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

    primary = llm_gemini.with_structured_output(schema)
    fallback = llm_groq.with_structured_output(schema)
    return primary.with_fallbacks([fallback])


__all__ = [
    "embeddings",
    "get_structured_model",
    "llm",
    "llm_fast",
    "llm_gemini",
    "llm_groq",
]
