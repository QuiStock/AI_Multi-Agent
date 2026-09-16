import logging
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qdrant_client import QdrantClient

from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.agents.faq.ingestion.indexer import Indexer
from src.agents.faq.ingestion.processing.models import Chunk
from src.agents.faq.ingestion.state.change_detector import (
    ChangeDetector,
    ChangeStatus,
)
from src.agents.faq.ingestion.state.manifest_store import ManifestStore
from src.agents.faq.ingestion.state.models import (
    IndexedDocumentState,
    IndexStatus,
    Manifest,
)
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore
from src.agents.faq.models import DocumentLoaded, DocumentPart
from src.agents.faq.retrieval.qdrant_retriever import QdrantRetriever


class FakeReaderRegistry:
    def __init__(
        self,
        events: list[tuple[str, str]],
        failing_doc_ids: frozenset[str] = frozenset(),
    ):
        self.events = events
        self.failing_doc_ids = failing_doc_ids

    def read(self, path: Path, *, doc_id: str) -> DocumentLoaded:
        self.events.append(("reader", doc_id))

        if doc_id in self.failing_doc_ids:
            raise RuntimeError(f"falha ao ler {doc_id}")

        return DocumentLoaded(
            doc_id=doc_id,
            source_name=path.name,
            file_type=path.suffix.lower(),
            parts=(
                DocumentPart(
                    index=0,
                    text=f"conteúdo de {doc_id}",
                ),
            ),
        )


class FakeNormalizer:
    def __init__(self, events: list[tuple[str, str]]):
        self.events = events

    def normalize(self, document: DocumentLoaded) -> DocumentLoaded:
        self.events.append(("normalizer", document.doc_id))
        return document


class FakeChunker:
    def __init__(self, events: list[tuple[str, str]]):
        self.events = events

    def chunk(self, document: DocumentLoaded) -> tuple[Chunk, ...]:
        self.events.append(("chunker", document.doc_id))
        return (
            Chunk(
                doc_id=document.doc_id,
                chunk_index=0,
                text=document.parts[0].text,
                metadata={
                    "source_name": document.source_name,
                    "file_type": document.file_type,
                    "part_index": 0,
                },
            ),
        )


class FakeEmbeddingProvider:
    def __init__(
        self,
        events: list[tuple[str, str]],
        failing_doc_ids: frozenset[str] = frozenset(),
    ):
        self.events = events
        self.failing_doc_ids = failing_doc_ids

    def embed_documents(
        self,
        chunks: tuple[Chunk, ...],
    ) -> list[list[float]]:
        doc_id = chunks[0].doc_id
        self.events.append(("embedding", doc_id))

        if doc_id in self.failing_doc_ids:
            raise RuntimeError(f"falha ao gerar embeddings para {doc_id}")

        return [[0.1, 0.2, 0.3] for _ in chunks]


class FakeEmbeddingModel:
    model = "fake-google-embedding"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeVectorStore:
    def __init__(
        self,
        events: list[tuple[str, str]],
        failing_doc_ids: frozenset[str] = frozenset(),
    ):
        self.events = events
        self.failing_doc_ids = failing_doc_ids
        self.replaced: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def replace_document(self, **kwargs: Any) -> None:
        doc_id = kwargs["doc_id"]
        self.events.append(("qdrant", doc_id))
        self.replaced.append(kwargs)

        if doc_id in self.failing_doc_ids:
            raise RuntimeError(f"falha ao salvar {doc_id}")

    def delete_by_document(self, *, doc_id: str) -> None:
        self.events.append(("qdrant_delete", doc_id))
        self.deleted.append(doc_id)


class RecordingManifestStore(ManifestStore):
    def __init__(self, manifest_path: Path, events: list[tuple[str, str]]):
        super().__init__(manifest_path)
        self.events = events

    def save(self, manifest: Manifest) -> None:
        self.events.append(("manifest", "save"))
        super().save(manifest)


@dataclass
class PipelineComponents:
    indexer: Indexer
    vector_store: FakeVectorStore
    manifest_store: ManifestStore
    events: list[tuple[str, str]]


def _make_components(
    docs_dir: Path,
    manifest_path: Path,
    *,
    failing_reads: frozenset[str] = frozenset(),
    failing_embeddings: frozenset[str] = frozenset(),
    failing_writes: frozenset[str] = frozenset(),
    record_manifest_events: bool = False,
) -> PipelineComponents:
    events: list[tuple[str, str]] = []
    vector_store = FakeVectorStore(events, failing_writes)
    manifest_store: ManifestStore = ManifestStore(manifest_path)

    if record_manifest_events:
        manifest_store = RecordingManifestStore(manifest_path, events)

    indexer = Indexer(
        documents_root=docs_dir,
        reader_registry=FakeReaderRegistry(events, failing_reads),
        normalizer=FakeNormalizer(events),
        chunker=FakeChunker(events),
        embedding_provider=FakeEmbeddingProvider(
            events,
            failing_embeddings,
        ),
        vector_store=vector_store,
        manifest_store=manifest_store,
        change_detector=ChangeDetector(),
        pipeline_version="faq-v1",
    )

    return PipelineComponents(
        indexer=indexer,
        vector_store=vector_store,
        manifest_store=manifest_store,
        events=events,
    )


def _create_docs(tmp_path: Path, *names: str) -> Path:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    for name in names:
        path = docs_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"conteúdo inicial de {name}", encoding="utf-8")

    return docs_dir


def test_change_detector_classifies_new_unchanged_modified_and_deleted(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "new.txt", "changed.md")
    unchanged = docs_dir / "unchanged.txt"
    unchanged.write_text("conteúdo estável", encoding="utf-8")

    detector = ChangeDetector()
    unchanged_hash = detector.calculate_hash(unchanged)
    changed_hash = detector.calculate_hash(docs_dir / "changed.md")

    manifest = Manifest(
        documents={
            "unchanged.txt": IndexedDocumentState(
                doc_id="unchanged.txt",
                source_hash=unchanged_hash,
                pipeline_version="faq-v1",
                chunk_count=1,
                status=IndexStatus.INDEXED,
            ),
            "changed.md": IndexedDocumentState(
                doc_id="changed.md",
                source_hash="hash-antigo",
                pipeline_version="faq-v1",
                chunk_count=1,
                status=IndexStatus.INDEXED,
            ),
            "removed.txt": IndexedDocumentState(
                doc_id="removed.txt",
                source_hash="hash-removido",
                pipeline_version="faq-v1",
                chunk_count=1,
                status=IndexStatus.INDEXED,
            ),
        }
    )

    changes = detector.detect(
        root=docs_dir,
        files=sorted(docs_dir.rglob("*")),
        manifest=manifest,
        pipeline_version="faq-v1",
    )

    statuses = {change.doc_id: change.status for change in changes}

    assert statuses == {
        "changed.md": ChangeStatus.MODIFIED,
        "new.txt": ChangeStatus.NEW,
        "unchanged.txt": ChangeStatus.UNCHANGED,
        "removed.txt": ChangeStatus.DELETED,
    }
    assert changed_hash != manifest.documents["changed.md"].source_hash


def test_change_detector_reindexes_when_pipeline_version_changes(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    path = docs_dir / "faq.txt"
    source_hash = ChangeDetector.calculate_hash(path)
    manifest = Manifest(
        documents={
            "faq.txt": IndexedDocumentState(
                doc_id="faq.txt",
                source_hash=source_hash,
                pipeline_version="faq-v1",
                chunk_count=1,
                status=IndexStatus.INDEXED,
            )
        }
    )

    changes = ChangeDetector().detect(
        root=docs_dir,
        files=[path],
        manifest=manifest,
        pipeline_version="faq-v2",
    )

    assert changes[0].status == ChangeStatus.MODIFIED


def test_change_detector_retries_a_previous_failed_document(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    path = docs_dir / "faq.txt"
    source_hash = ChangeDetector.calculate_hash(path)
    manifest = Manifest(
        documents={
            "faq.txt": IndexedDocumentState(
                doc_id="faq.txt",
                source_hash=source_hash,
                pipeline_version="faq-v1",
                chunk_count=0,
                status=IndexStatus.FAILED,
                error="falha anterior",
            )
        }
    )

    changes = ChangeDetector().detect(
        root=docs_dir,
        files=[path],
        manifest=manifest,
        pipeline_version="faq-v1",
    )

    assert changes[0].status == ChangeStatus.MODIFIED


def test_indexer_indexes_new_documents_and_persists_manifest(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "a.txt", "nested/b.md")
    manifest_path = tmp_path / "manifest.json"
    components = _make_components(
        docs_dir,
        manifest_path,
        record_manifest_events=True,
    )

    summary = components.indexer.run()

    assert summary.indexed == 2
    assert summary.skipped == 0
    assert summary.failed == 0
    assert {item[0] for item in components.events} == {
        "reader",
        "normalizer",
        "chunker",
        "embedding",
        "qdrant",
        "manifest",
    }

    manifest = ManifestStore(manifest_path).load()
    assert set(manifest.documents) == {"a.txt", "nested/b.md"}
    assert all(
        state.status == IndexStatus.INDEXED for state in manifest.documents.values()
    )


def test_indexer_skips_unchanged_documents_on_next_run(tmp_path: Path) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    manifest_path = tmp_path / "manifest.json"

    _make_components(docs_dir, manifest_path).indexer.run()
    second_run = _make_components(docs_dir, manifest_path)

    summary = second_run.indexer.run()

    assert summary.indexed == 0
    assert summary.skipped == 1
    assert second_run.events == []


def test_indexer_reindexes_modified_document(tmp_path: Path) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    manifest_path = tmp_path / "manifest.json"

    first_run = _make_components(docs_dir, manifest_path)
    first_run.indexer.run()
    first_hash = first_run.manifest_store.load().documents["faq.txt"].source_hash

    (docs_dir / "faq.txt").write_text(
        "conteúdo modificado",
        encoding="utf-8",
    )

    second_run = _make_components(docs_dir, manifest_path)
    summary = second_run.indexer.run()

    second_hash = second_run.manifest_store.load().documents["faq.txt"].source_hash

    assert summary.indexed == 1
    assert summary.skipped == 0
    assert first_hash != second_hash


def test_indexer_removes_deleted_document_from_vector_store_and_manifest(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    manifest_path = tmp_path / "manifest.json"

    _make_components(docs_dir, manifest_path).indexer.run()
    (docs_dir / "faq.txt").unlink()

    second_run = _make_components(docs_dir, manifest_path)
    summary = second_run.indexer.run()

    assert summary.deleted == 1
    assert second_run.vector_store.deleted == ["faq.txt"]
    assert ManifestStore(manifest_path).load().documents == {}


def test_indexer_marks_reader_failure_and_continues_with_other_documents(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "ok.txt", "broken.txt")
    manifest_path = tmp_path / "manifest.json"
    components = _make_components(
        docs_dir,
        manifest_path,
        failing_reads=frozenset({"broken.txt"}),
    )

    summary = components.indexer.run()
    manifest = ManifestStore(manifest_path).load()

    assert summary.indexed == 1
    assert summary.failed == 1
    assert manifest.documents["ok.txt"].status == IndexStatus.INDEXED
    assert manifest.documents["broken.txt"].status == IndexStatus.FAILED
    assert "falha ao ler broken.txt" in (manifest.documents["broken.txt"].error or "")


def test_indexer_marks_qdrant_failure_without_marking_document_indexed(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "ok.txt", "broken.txt")
    manifest_path = tmp_path / "manifest.json"
    components = _make_components(
        docs_dir,
        manifest_path,
        failing_writes=frozenset({"broken.txt"}),
    )

    summary = components.indexer.run()
    manifest = ManifestStore(manifest_path).load()

    assert summary.indexed == 1
    assert summary.failed == 1
    assert manifest.documents["ok.txt"].status == IndexStatus.INDEXED
    assert manifest.documents["broken.txt"].status == IndexStatus.FAILED
    assert manifest.documents["broken.txt"].chunk_count == 0


def test_indexer_marks_embedding_failure_without_calling_qdrant(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "broken.txt")
    manifest_path = tmp_path / "manifest.json"
    components = _make_components(
        docs_dir,
        manifest_path,
        failing_embeddings=frozenset({"broken.txt"}),
    )

    summary = components.indexer.run()
    manifest = ManifestStore(manifest_path).load()

    assert summary.indexed == 0
    assert summary.failed == 1
    assert manifest.documents["broken.txt"].status == IndexStatus.FAILED
    assert components.vector_store.replaced == []


def test_indexer_preserves_processing_order_before_manifest_save(
    tmp_path: Path,
) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    components = _make_components(
        docs_dir,
        tmp_path / "manifest.json",
        record_manifest_events=True,
    )

    components.indexer.run()

    assert components.events == [
        ("reader", "faq.txt"),
        ("normalizer", "faq.txt"),
        ("chunker", "faq.txt"),
        ("embedding", "faq.txt"),
        ("qdrant", "faq.txt"),
        ("manifest", "save"),
    ]


def test_indexer_logs_summary_and_document_metrics(
    tmp_path: Path,
    caplog: Any,
) -> None:
    docs_dir = _create_docs(tmp_path, "faq.txt")
    components = _make_components(
        docs_dir,
        tmp_path / "manifest.json",
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.faq.ingestion.indexer",
    ):
        components.indexer.run()

    finished = next(
        record for record in caplog.records if record.message == "faq_indexing_finished"
    )
    indexed = next(
        record for record in caplog.records if record.message == "faq_document_indexed"
    )

    assert finished.files_discovered == 1
    assert finished.indexed == 1
    assert finished.skipped == 0
    assert finished.deleted == 0
    assert finished.failed == 0
    assert finished.duration_ms >= 0
    assert indexed.doc_id == "faq.txt"
    assert indexed.chunk_count == 1
    assert indexed.embedding_count == 1
    assert indexed.duration_ms >= 0


def test_indexer_logs_document_failure(
    tmp_path: Path,
    caplog: Any,
) -> None:
    docs_dir = _create_docs(tmp_path, "broken.txt")
    components = _make_components(
        docs_dir,
        tmp_path / "manifest.json",
        failing_embeddings=frozenset({"broken.txt"}),
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.faq.ingestion.indexer",
    ):
        components.indexer.run()

    failed = next(
        record
        for record in caplog.records
        if record.message == "faq_document_indexing_failed"
    )

    assert failed.doc_id == "broken.txt"
    assert failed.chunk_count == 1
    assert failed.embedding_count == 0
    assert failed.duration_ms >= 0


def test_embedding_provider_logs_count_dimension_and_duration(
    caplog: Any,
) -> None:
    provider = GoogleEmbeddingProvider(FakeEmbeddingModel())
    chunks = (
        Chunk(
            doc_id="faq.txt",
            chunk_index=0,
            text="conteúdo",
        ),
    )

    with caplog.at_level(
        logging.INFO,
        logger=("src.agents.faq.ingestion.embedding.google_embedding_provider"),
    ):
        vectors = provider.embed_documents(chunks)

    finished = next(
        record
        for record in caplog.records
        if record.message == "faq_embeddings_finished"
    )

    assert len(vectors) == 1
    assert finished.chunk_count == 1
    assert finished.embedding_count == 1
    assert finished.vector_dimension == 3
    assert finished.duration_ms >= 0


def test_qdrant_store_logs_inserted_and_removed_points(
    caplog: Any,
) -> None:
    store = QdrantStore(
        qdrant_client=QdrantClient(":memory:"),
        collection_name="faq_logging_test",
    )
    chunk = Chunk(
        doc_id="faq.txt",
        chunk_index=0,
        text="conteúdo",
        metadata={
            "source_name": "faq.txt",
            "file_type": ".txt",
            "part_index": 0,
        },
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.faq.ingestion.vectorstore.qdrant_store",
    ):
        store.replace_document(
            doc_id="faq.txt",
            source_hash="hash-1",
            pipeline_version="faq-v1",
            chunks=[chunk],
            vectors=[[0.1, 0.2, 0.3]],
        )
        store.replace_document(
            doc_id="faq.txt",
            source_hash="hash-2",
            pipeline_version="faq-v1",
            chunks=[chunk],
            vectors=[[0.1, 0.2, 0.3]],
        )
        store.delete_by_document(doc_id="faq.txt")

    replaced = [
        record
        for record in caplog.records
        if record.message == "qdrant_document_replaced"
    ]
    old_versions_deleted = [
        record
        for record in caplog.records
        if record.message == "qdrant_old_versions_deleted"
    ]
    deleted = next(
        record
        for record in caplog.records
        if record.message == "qdrant_document_deleted"
    )

    assert len(replaced) == 2
    assert all(record.points_inserted == 1 for record in replaced)
    assert [record.points_removed for record in old_versions_deleted] == [0, 1]
    assert deleted.points_removed == 1
    assert all(record.duration_ms >= 0 for record in replaced)
    assert deleted.duration_ms >= 0


def test_qdrant_retriever_logs_candidates_and_results(
    caplog: Any,
) -> None:
    class QueryEmbeddings:
        def embed_query(self, query: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    class QueryVectorStore:
        def search(
            self,
            *,
            query_vector: list[float],
            limit: int,
        ) -> list[Any]:
            return [
                SimpleNamespace(
                    score=0.9,
                    payload={
                        "source_name": "faq.md",
                        "text": "conteúdo",
                        "page_number": None,
                    },
                ),
                SimpleNamespace(
                    score=0.8,
                    payload={
                        "source_name": "manual.pdf",
                        "text": "manual",
                        "page_number": 2,
                    },
                ),
            ]

    retriever = QdrantRetriever(
        embedding_provider=QueryEmbeddings(),
        vector_store=QueryVectorStore(),
        top_k=2,
        min_score=0.3,
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.agents.faq.retrieval.qdrant_retriever",
    ):
        results = retriever.search("qual é a regra?")

    finished = next(
        record
        for record in caplog.records
        if record.message == "faq_retrieval_finished"
    )

    assert len(results) == 2
    assert finished.candidates_count == 2
    assert finished.results_count == 2
    assert finished.no_results is False
    assert finished.duration_ms >= 0
