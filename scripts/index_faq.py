from __future__ import annotations

from pathlib import Path
from typing import Any

from pymongo import MongoClient

from src import config
from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.agents.faq.ingestion.indexer import Indexer
from src.agents.faq.ingestion.processing.chunker import (
    RecursiveCharacterChunker,
)
from src.agents.faq.ingestion.processing.models import ChunkingConfig
from src.agents.faq.ingestion.processing.normalizer import DocumentNormalizer
from src.agents.faq.ingestion.readers.reader_registry import (
    create_default_registry,
)
from src.agents.faq.ingestion.state.change_detector import ChangeDetector
from src.agents.faq.ingestion.state.manifest_store import ManifestStore
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore
from src.observability.ai_usage_repository import (
    AI_USAGE_COLLECTION_NAME,
    MongoAIUsageRepository,
)

PIPELINE_VERSION = "faq-v2-audience-v1"


def build_indexer(
    settings: config.Settings,
    *,
    usage_repository: MongoAIUsageRepository | None = None,
) -> Indexer:
    documents_root = settings.faq_docs_dir
    if documents_root is None:
        raise RuntimeError("FAQ_DOCS_DIR não foi configurado")

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY é obrigatório para gerar embeddings")

    qdrant = config.create_qdrant_client(settings)
    manifest_path = settings.faq_data_dir / "faq_manifest.json"

    return Indexer(
        documents_root=Path(documents_root),
        reader_registry=create_default_registry(),
        normalizer=DocumentNormalizer(),
        chunker=RecursiveCharacterChunker(
            ChunkingConfig(
                max_chars=settings.faq_chunk_size,
                overlap_chars=settings.faq_chunk_overlap,
            )
        ),
        embedding_provider=GoogleEmbeddingProvider(usage_repository=usage_repository),
        vector_store=QdrantStore(
            qdrant_client=qdrant,
            collection_name=settings.faq_vectorstore_collection,
        ),
        manifest_store=ManifestStore(manifest_path),
        change_detector=ChangeDetector(),
        pipeline_version=PIPELINE_VERSION,
    )


def main() -> None:
    settings = config.get_settings()
    mongo_client: MongoClient[Any] | None = None
    usage_repository = None
    if settings.mongodb_uri and settings.mongodb_db:
        mongo_client = MongoClient(settings.mongodb_uri)
        usage_repository = MongoAIUsageRepository(
            mongo_client[settings.mongodb_db][AI_USAGE_COLLECTION_NAME]
        )
    try:
        summary = build_indexer(
            settings,
            usage_repository=usage_repository,
        ).run()
    finally:
        if mongo_client is not None:
            mongo_client.close()

    print(
        "FAQ indexada: "
        f"indexed={summary.indexed}, "
        f"skipped={summary.skipped}, "
        f"deleted={summary.deleted}, "
        f"failed={summary.failed}"
    )

    if summary.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
