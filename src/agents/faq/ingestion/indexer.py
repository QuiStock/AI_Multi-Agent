import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.agents.faq.ingestion.processing.chunker import Chunker
from src.agents.faq.ingestion.processing.normalizer import DocumentNormalizer
from src.agents.faq.ingestion.readers.reader_registry import ReaderRegistry
from src.agents.faq.ingestion.state.change_detector import (
    ChangeDetector,
    ChangeStatus,
    DetectedChange,
)
from src.agents.faq.ingestion.state.manifest_store import ManifestStore
from src.agents.faq.ingestion.state.models import (
    IndexedDocumentState,
    IndexStatus,
    Manifest,
)
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf"})


@dataclass
class IndexingSummary:
    indexed: int = 0
    skipped: int = 0
    deleted: int = 0
    failed: int = 0


class Indexer:
    def __init__(  # noqa: PLR0913 - explicit dependency-injection boundary
        self,
        *,
        documents_root: Path,
        reader_registry: ReaderRegistry,
        normalizer: DocumentNormalizer,
        chunker: Chunker,
        embedding_provider: GoogleEmbeddingProvider,
        vector_store: QdrantStore,
        manifest_store: ManifestStore,
        change_detector: ChangeDetector,
        pipeline_version: str,
    ):
        self.documents_root = documents_root
        self.reader_registry = reader_registry
        self.normalizer = normalizer
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.manifest_store = manifest_store
        self.change_detector = change_detector
        self.pipeline_version = pipeline_version

    def run(self) -> IndexingSummary:
        started_at = perf_counter()
        summary = IndexingSummary()
        files_discovered = 0

        logger.info(
            "faq_indexing_started",
            extra={
                "documents_root": str(self.documents_root),
                "pipeline_version": self.pipeline_version,
            },
        )

        try:
            manifest = self.manifest_store.load()
            current_files = self._discover_files()
            files_discovered = len(current_files)

            logger.info(
                "faq_documents_discovered",
                extra={
                    "files_discovered": files_discovered,
                },
            )

            changes = self.change_detector.detect(
                root=self.documents_root,
                files=current_files,
                manifest=manifest,
                pipeline_version=self.pipeline_version,
            )

            for change in changes:
                if change.status == ChangeStatus.UNCHANGED:
                    summary.skipped += 1
                    continue

                if change.status == ChangeStatus.DELETED:
                    self._handle_deleted(
                        doc_id=change.doc_id,
                        manifest=manifest,
                        summary=summary,
                    )
                    continue

                self._handle_document(
                    change=change,
                    manifest=manifest,
                    summary=summary,
                )

            return summary

        except Exception:
            logger.exception("faq_indexing_failed")
            raise
        finally:
            logger.info(
                "faq_indexing_finished",
                extra={
                    "files_discovered": files_discovered,
                    "indexed": summary.indexed,
                    "skipped": summary.skipped,
                    "deleted": summary.deleted,
                    "failed": summary.failed,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )

    def _discover_files(self) -> list[Path]:
        if not self.documents_root.exists():
            return []

        return sorted(
            path
            for path in self.documents_root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )

    def _handle_document(
        self,
        *,
        change: DetectedChange,
        manifest: Manifest,
        summary: IndexingSummary,
    ) -> None:

        started_at = perf_counter()
        chunk_count = 0
        embedding_count = 0

        logger.info(
            "faq_document_indexing_started",
            extra={
                "doc_id": change.doc_id,
                "status": change.status.value,
                "path": str(change.path) if change.path else None,
            },
        )

        if change.path is None or change.source_hash is None:
            raise RuntimeError(
                "Uma alteração de documento precisa de path e source_hash."
            )

        try:
            document = self.reader_registry.read(
                change.path,
                doc_id=change.doc_id,
            )
            normalized_document = self.normalizer.normalize(document)
            chunks = self.chunker.chunk(normalized_document)
            chunk_count = len(chunks)
            vectors = self.embedding_provider.embed_documents(chunks)
            embedding_count = len(vectors)

            self.vector_store.replace_document(
                doc_id=change.doc_id,
                source_hash=change.source_hash,
                pipeline_version=self.pipeline_version,
                chunks=chunks,
                vectors=vectors,
            )

            manifest.documents[change.doc_id] = IndexedDocumentState(
                doc_id=change.doc_id,
                source_hash=change.source_hash,
                pipeline_version=self.pipeline_version,
                chunk_count=chunk_count,
                status=IndexStatus.INDEXED,
                indexed_at=self._now(),
                error=None,
            )

            self.manifest_store.save(manifest)
            summary.indexed += 1

            logger.info(
                "faq_document_indexed",
                extra={
                    "doc_id": change.doc_id,
                    "status": change.status.value,
                    "path": str(change.path),
                    "chunk_count": chunk_count,
                    "embedding_count": embedding_count,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )

        except Exception as exc:
            logger.exception(
                "faq_document_indexing_failed",
                extra={
                    "doc_id": change.doc_id,
                    "chunk_count": chunk_count,
                    "embedding_count": embedding_count,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )

            self._mark_failed(
                manifest=manifest,
                doc_id=change.doc_id,
                source_hash=change.source_hash,
                error_message=str(exc),
            )
            self.manifest_store.save(manifest)
            summary.failed += 1

    def _handle_deleted(
        self,
        *,
        doc_id: str,
        manifest: Manifest,
        summary: IndexingSummary,
    ) -> None:
        started_at = perf_counter()

        try:
            self.vector_store.delete_by_document(doc_id=doc_id)
            manifest.documents.pop(doc_id, None)
            self.manifest_store.save(manifest)
            summary.deleted += 1

            logger.info(
                "faq_document_deleted",
                extra={
                    "doc_id": doc_id,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )

        except Exception as exc:
            logger.exception(
                "faq_document_deletion_failed",
                extra={
                    "doc_id": doc_id,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            previous_state = manifest.documents.get(doc_id)
            self._mark_failed(
                manifest=manifest,
                doc_id=doc_id,
                source_hash=(
                    previous_state.source_hash if previous_state is not None else ""
                ),
                error_message=str(exc),
            )
            self.manifest_store.save(manifest)
            summary.failed += 1

    def _mark_failed(
        self,
        *,
        manifest: Manifest,
        doc_id: str,
        source_hash: str,
        error_message: str,
    ) -> None:
        manifest.documents[doc_id] = IndexedDocumentState(
            doc_id=doc_id,
            source_hash=source_hash,
            pipeline_version=self.pipeline_version,
            chunk_count=0,
            status=IndexStatus.FAILED,
            indexed_at=None,
            error=error_message,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
