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

llm_groq = ChatGroq(
    model=config.GROQ_CHAT_MODEL,
    temperature=config.LLM_TEMPERATURE,
    model_kwargs={"top_p": config.LLM_TOP_P},
    api_key=_secret(config.GROQ_API_KEY, "groq"),
)

# The remaining title-generation task uses Hugging Face's OpenAI-compatible
# router through the already-installed Groq client, avoiding another SDK.
llm_huggingface = ChatGroq(
    model=config.HF_TITLE_MODEL,
    temperature=0.0,
    api_key=_secret(config.HF_TOKEN, "huggingface"),
    base_url="https://router.huggingface.co/v1",
)

llm = llm_gemini

embeddings = GoogleGenerativeAIEmbeddings(
    model=config.GEMINI_EMBEDDING_MODEL,
    api_key=_secret(config.GEMINI_API_KEY, "gemini"),
    output_dimensionality=768,
)


SchemaT = TypeVar("SchemaT", bound=BaseModel)
StructuredModelProvider = Literal["gemini", "groq"]


def get_structured_model(
    schema: type[SchemaT],
    *,
    provider: StructuredModelProvider = "gemini",
) -> Runnable[Any, Any]:
    """Bind a schema to the selected provider's structured-output model."""
    model = llm_gemini if provider == "gemini" else llm_groq
    return model.with_structured_output(schema)


def get_title_model(schema: type[SchemaT]) -> Runnable[Any, Any]:
    """Return Hugging Face structured output for low-volume title generation."""
    return llm_huggingface.with_structured_output(schema)


__all__ = [
    "embeddings",
    "get_structured_model",
    "get_title_model",
    "llm",
    "llm_gemini",
    "llm_huggingface",
    "llm_groq",
]
