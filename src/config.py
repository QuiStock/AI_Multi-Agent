from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SettingsError(RuntimeError):
    """Raised when required application settings are missing."""


class Settings(BaseSettings):
    """Application settings loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    # Credentials
    gemini_api_key: str | None = None
    groq_api_key: str | None = None

    # Models
    gemini_chat_model: str = "gemini-3.6-flash"
    gemini_embedding_model: str = "gemini-embedding-2-preview"
    groq_chat_model: str = "llama-3.3-70b-versatile"
    groq_fast_model: str = "llama-3.3-70b-versatile"

    # Model parameters
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_top_p: float = Field(default=0.95, ge=0.0, le=1.0)

    # Optional settings already present in the local .env file
    database_url: str | None = None
    postgres_password: str | None = None
    mongodb_uri: str | None = None
    mongodb_db: str | None = None

    # FAQ RAG directories
    faq_data_dir: Path = PROJECT_ROOT / "src" / "data"
    faq_docs_dir: Path | None = None
    faq_vectorstore_dir: Path | None = None
    faq_metadata_file: Path | None = None

    # FAQ RAG parameters
    faq_chunk_size: int = Field(default=1000, gt=0)
    faq_chunk_overlap: int = Field(default=200, ge=0)
    faq_retrieval_k: int = Field(default=4, gt=0)
    faq_retrieval_min_relevance: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
    )

    @model_validator(mode="after")
    def configure_faq_paths(self) -> Settings:
        """Derive FAQ paths from FAQ_DATA_DIR when specific paths are absent."""
        if self.faq_docs_dir is None:
            self.faq_docs_dir = self.faq_data_dir / "docs"

        if self.faq_vectorstore_dir is None:
            self.faq_vectorstore_dir = self.faq_data_dir / "vectorstore"

        if self.faq_metadata_file is None:
            self.faq_metadata_file = self.faq_data_dir / "metadata.json"

        if self.faq_chunk_overlap >= self.faq_chunk_size:
            raise ValueError(
                "FAQ_CHUNK_OVERLAP deve ser menor que FAQ_CHUNK_SIZE"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()


def validate_required_settings(
    current_settings: Settings | None = None,
) -> Settings:
    """Validate the credentials required by the configured LLM providers."""
    current_settings = current_settings or get_settings()
    missing_variables: list[str] = []

    if (
        not current_settings.gemini_api_key
        or not current_settings.gemini_api_key.strip()
    ):
        missing_variables.append("GEMINI_API_KEY")

    if not current_settings.groq_api_key or not current_settings.groq_api_key.strip():
        missing_variables.append("GROQ_API_KEY")

    if missing_variables:
        variables = ", ".join(missing_variables)
        raise SettingsError(
            f"Variáveis obrigatórias não preenchidas: {variables}"
        )

    return current_settings


settings = get_settings()

# Compatibility aliases: existing modules can continue using config.CONSTANT.
FAQ_DATA_DIR = settings.faq_data_dir
FAQ_DOCS_DIR = cast(Path, settings.faq_docs_dir)
FAQ_VECTORSTORE_DIR = cast(Path, settings.faq_vectorstore_dir)
FAQ_METADATA_FILE = cast(Path, settings.faq_metadata_file)

FAQ_CHUNK_SIZE = settings.faq_chunk_size
FAQ_CHUNK_OVERLAP = settings.faq_chunk_overlap
FAQ_RETRIEVAL_K = settings.faq_retrieval_k
FAQ_RETRIEVAL_MIN_RELEVANCE = settings.faq_retrieval_min_relevance

GEMINI_API_KEY = settings.gemini_api_key
GROQ_API_KEY = settings.groq_api_key

GEMINI_CHAT_MODEL = settings.gemini_chat_model
GEMINI_EMBEDDING_MODEL = settings.gemini_embedding_model
GROQ_CHAT_MODEL = settings.groq_chat_model
GROQ_FAST_MODEL = settings.groq_fast_model
LLM_TEMPERATURE = settings.llm_temperature
LLM_TOP_P = settings.llm_top_p
