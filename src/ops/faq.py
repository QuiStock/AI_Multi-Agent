"""Check bundled FAQ documents; index explicitly with --apply.

The manifest is persisted in MongoDB between one-off Kubernetes Jobs. Local
temporary files are writable even when the runtime source tree is read-only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from src import config
from src.ops.memory import check_vector_collection
from src.agents.faq.ingestion.indexer import SUPPORTED_EXTENSIONS, Indexer
from src.agents.faq.ingestion.processing.chunker import RecursiveCharacterChunker
from src.agents.faq.ingestion.processing.models import ChunkingConfig
from src.agents.faq.ingestion.processing.normalizer import DocumentNormalizer
from src.agents.faq.ingestion.readers.reader_registry import create_default_registry
from src.agents.faq.ingestion.state.change_detector import ChangeDetector
from src.agents.faq.ingestion.state.manifest_store import ManifestStore
from src.agents.faq.ingestion.state.models import Manifest
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore


class MongoManifestStore(ManifestStore):
    """Persist the existing manifest format without storing credentials."""

    def __init__(self, path: Path, collection: Any, key: str) -> None:
        super().__init__(path)
        self._collection = collection
        self._key = key
        previous = collection.find_one({"_id": key})
        if previous is not None:
            path.write_text(previous["manifest_json"], encoding="utf-8")

    def save(self, manifest: Manifest) -> None:
        super().save(manifest)
        self._collection.update_one(
            {"_id": self._key},
            {"$set": {"manifest_json": self.manifest_path.read_text(encoding="utf-8")}},
            upsert=True,
        )


def discover_documents(root: Path) -> list[Path]:
    documents = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    if not documents:
        raise ValueError("No FAQ documents found; refusing an empty indexing run")
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = config.get_settings()
    root = settings.faq_docs_dir
    if root is None:
        parser.error("FAQ_DOCS_DIR is required")
    documents = discover_documents(root)
    client = config.create_qdrant_client(settings)
    try:
        points = check_vector_collection(
            client, settings.faq_vectorstore_collection, 768
        )
        if not args.apply:
            exists = client.collection_exists(settings.faq_vectorstore_collection)
            print(
                json.dumps(
                    {
                        "mode": "check",
                        "documents": len(documents),
                        "collection_exists": exists,
                        "points": points,
                    }
                )
            )
            return
        if not settings.mongodb_uri or not settings.mongodb_db:
            parser.error("MongoDB is required for the persistent FAQ manifest")
        # Import the provider only for apply; check never calls an embedding model.
        from src.agents.faq.ingestion.embedding.google_embedding_provider import (
            GoogleEmbeddingProvider,
        )

        with (
            MongoClient[Any](settings.mongodb_uri) as mongo,
            tempfile.TemporaryDirectory() as directory,
        ):
            store = MongoManifestStore(
                Path(directory) / "manifest.json",
                mongo[settings.mongodb_db]["faq_ingestion_manifests"],
                settings.faq_vectorstore_collection,
            )
            if points and not store.load().documents:
                raise RuntimeError(
                    "Populated FAQ requires an existing manifest or a separate migration"
                )
            summary = Indexer(
                documents_root=root,
                reader_registry=create_default_registry(),
                normalizer=DocumentNormalizer(),
                chunker=RecursiveCharacterChunker(
                    ChunkingConfig(
                        max_chars=settings.faq_chunk_size,
                        overlap_chars=settings.faq_chunk_overlap,
                    )
                ),
                embedding_provider=GoogleEmbeddingProvider(),
                vector_store=QdrantStore(client, settings.faq_vectorstore_collection),
                manifest_store=store,
                change_detector=ChangeDetector(),
                pipeline_version=f"faq-v2:{settings.gemini_embedding_model}",
            ).run()
            print(json.dumps({"mode": "apply", **asdict(summary)}))
            if summary.failed:
                raise RuntimeError("FAQ indexing has failed documents")
    finally:
        client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"FAQ operation failed ({type(error).__name__})") from None
