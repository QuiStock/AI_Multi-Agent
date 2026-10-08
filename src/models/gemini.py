"""Compatibility accessors for the centralized LLM factory."""

from typing import Any

from src.llm_factory import embeddings, llm_openai


def get_chat_model() -> Any:
    """Return the configured primary chat model."""

    return llm_openai


def get_embeddings() -> Any:
    """Return the centralized Gemini embedding model."""

    return embeddings
