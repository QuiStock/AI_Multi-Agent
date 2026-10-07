from __future__ import annotations

from pathlib import Path

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

PIPELINE_VERSION = "faq-v2-audience-v1"


def build_indexer(settings: config.Settings) -> Indexer:
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
        embedding_provider=GoogleEmbeddingProvider(),
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
    summary = build_indexer(settings).run()

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
