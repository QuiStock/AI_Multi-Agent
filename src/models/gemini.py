from typing import Any

from src.llm_factory import embeddings, llm_gemini


def get_chat_model() -> Any:
    """Compatibility accessor for the primary Gemini model."""

    return llm_gemini


def get_embeddings() -> Any:
    """Compatibility accessor for the centralized embedding model."""

    return embeddings
