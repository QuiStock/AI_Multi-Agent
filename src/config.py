from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient

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

    # Deployment metadata
    app_environment: Literal["development", "qa", "production"] = "development"

    # Credentials
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # Legacy .env values are accepted for compatibility but are unused at runtime.
    groq_api_key: str | None = None
    hf_token: str | None = None

    # Models
    openai_model: str = "gpt-6-luna"
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_tier: Literal["free", "paid"] = "free"
    # Legacy .env values are accepted for compatibility but are unused at runtime.
    gemini_chat_model: str = "gemini-3.6-flash"
    groq_chat_model: str = "qwen/qwen3.8-27b"
    hf_title_model: str = "openai/gpt-oss-20b:fastest"

    # Model parameters
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_top_p: float = Field(default=0.95, ge=0.0, le=1.0)

    # Optional settings already present in the local .env file
    database_url: str | None = None
    postgres_password: str | None = None
    postgres_dsn: str | None = None
    jwt_secret: str | None = None
    auth_bypass_local_tests: bool = False
    auth_bypass_email: str = "jwt-bypass@localhost.invalid"
    auth_bypass_role_id: int = 2
    postgres_pool_timeout_seconds: float = Field(default=2.0, gt=0)
    health_probe_timeout_seconds: float = Field(default=2.0, gt=0)
    mongodb_uri: str | None = None
    mongodb_db: str | None = None
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    summary_queue_stream: str = "quistock:conversation-summary"
    summary_queue_group: str = "summary-workers"
    summary_job_max_attempts: int = Field(default=5, ge=1, le=10)
    summary_reconciliation_interval_seconds: int = Field(default=60, ge=1)
    memory_conversations_collection: str = "conversations"
    memory_summary_jobs_collection: str = "conversation_summary_jobs"
    memory_summary_locks_collection: str = "conversation_summary_locks"

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
    faq_vectorstore_collection: str = "faq_v2"

    # Conversational memory retrieval
    memory_summary_collection: str = "conversation_summaries"
    memory_summary_top_k: int = Field(default=3, ge=1, le=3)
    memory_summary_min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    memory_summary_fallback_limit: int = Field(default=3, ge=1, le=3)

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
            raise ValueError("FAQ_CHUNK_OVERLAP deve ser menor que FAQ_CHUNK_SIZE")

        return self


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()


def validate_required_settings(
    current_settings: Settings | None = None,
) -> Settings:
    """Validate chat and embedding provider credentials."""
    current_settings = current_settings or get_settings()
    missing_variables: list[str] = []

    if (
        not current_settings.openai_api_key
        or not current_settings.openai_api_key.strip()
    ):
        missing_variables.append("OPENAI_API_KEY")

    if (
        not current_settings.gemini_api_key
        or not current_settings.gemini_api_key.strip()
    ):
        missing_variables.append("GEMINI_API_KEY")

    if missing_variables:
        variables = ", ".join(missing_variables)
        raise SettingsError(f"Variáveis obrigatórias não preenchidas: {variables}")

    return current_settings


def create_qdrant_client(
    current_settings: Settings | None = None,
    *,
    timeout: int | None = None,
) -> QdrantClient:
    """Create the Qdrant Cloud client from the configured URL and API key."""
    current_settings = current_settings or get_settings()
    if not current_settings.qdrant_url or not current_settings.qdrant_api_key:
        raise SettingsError(
            "QDRANT_URL e QDRANT_API_KEY são obrigatórios para o Qdrant Cloud"
        )

    return QdrantClient(
        url=current_settings.qdrant_url,
        api_key=current_settings.qdrant_api_key,
        timeout=timeout,
    )


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

MEMORY_SUMMARY_COLLECTION = settings.memory_summary_collection
MEMORY_SUMMARY_TOP_K = settings.memory_summary_top_k
MEMORY_SUMMARY_MIN_SCORE = settings.memory_summary_min_score
MEMORY_SUMMARY_FALLBACK_LIMIT = settings.memory_summary_fallback_limit

OPENAI_API_KEY = settings.openai_api_key
OPENAI_MODEL = settings.openai_model
GEMINI_API_KEY = settings.gemini_api_key
QDRANT_URL = settings.qdrant_url
QDRANT_API_KEY = settings.qdrant_api_key

GEMINI_EMBEDDING_MODEL = settings.gemini_embedding_model
