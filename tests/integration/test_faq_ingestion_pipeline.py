from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from shutil import rmtree

import pytest
from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient

from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.agents.faq.ingestion.indexer import Indexer
from src.agents.faq.ingestion.processing.chunker import RecursiveCharacterChunker
from src.agents.faq.ingestion.processing.models import Chunk, ChunkingConfig
from src.agents.faq.ingestion.processing.normalizer import DocumentNormalizer
from src.agents.faq.ingestion.readers.base_reader import (
    DocumentReaderError,
    UnsupportedFileTypeError,
)
from src.agents.faq.ingestion.readers.reader_registry import (
    create_default_registry,
)
from src.agents.faq.ingestion.state.change_detector import ChangeDetector
from src.agents.faq.ingestion.state.manifest_store import ManifestStore
from src.agents.faq.ingestion.state.models import IndexStatus
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore
from src.agents.faq.models import DocumentLoaded, DocumentPart

pytestmark = pytest.mark.integration


@pytest.fixture
def integration_tmp_path() -> Iterator[Path]:
    temporary_root = Path.cwd() / "tmp"
    temporary_root.mkdir(exist_ok=True)
    directory = temporary_root / ".pytest-integration-fixtures"
    rmtree(directory, ignore_errors=True)
    directory.mkdir()

    try:
        yield directory
    finally:
        rmtree(directory, ignore_errors=True)


class DeterministicEmbeddings(Embeddings):
    def _vector(self, text: str) -> list[float]:
        return [float((index + len(text)) % 10) for index in range(8)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def _make_pdf(path: Path) -> None:
    stream = b"BT /F1 12 Tf 72 720 Td (Regra em PDF.) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
        + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(content))
        content += f"{index} 0 obj\n".encode("ascii")
        content += body
        content += b"\nendobj\n"

    xref_position = len(content)
    content += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    content += b"0000000000 65535 f \n"
    for offset in offsets:
        content += f"{offset:010d} 00000 n \n".encode("ascii")
    content += b"trailer\n"
    content += f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode("ascii")
    content += b"startxref\n"
    content += f"{xref_position}\n".encode("ascii")
    content += b"%%EOF\n"
    path.write_bytes(bytes(content))


def _make_indexer(
    documents_root: Path,
    manifest_path: Path,
    vector_store: QdrantStore,
) -> Indexer:
    return Indexer(
        documents_root=documents_root,
        reader_registry=create_default_registry(),
        normalizer=DocumentNormalizer(),
        chunker=RecursiveCharacterChunker(
            ChunkingConfig(max_chars=40, overlap_chars=5)
        ),
        embedding_provider=GoogleEmbeddingProvider(DeterministicEmbeddings()),
        vector_store=vector_store,
        manifest_store=ManifestStore(manifest_path),
        change_detector=ChangeDetector(),
        pipeline_version="integration-v1",
    )


def test_ingestion_pipeline_indexes_updates_and_deletes_documents(
    integration_tmp_path: Path,
) -> None:
    tmp_path = integration_tmp_path
    documents_root = tmp_path / "docs"
    documents_root.mkdir()
    (documents_root / "faq.txt").write_text(
        "Regra inicial.\r\n\r\n\r\nDetalhes.",
        encoding="utf-8",
    )
    (documents_root / "manual.md").write_text(
        "# Manual\n\nConteúdo documentado.",
        encoding="utf-8",
    )
    _make_pdf(documents_root / "manual.pdf")

    vector_store = QdrantStore(
        qdrant_client=QdrantClient(":memory:"),
        collection_name="faq_integration",
    )
    manifest_path = tmp_path / "manifest.json"
    indexer = _make_indexer(documents_root, manifest_path, vector_store)

    first = indexer.run()

    assert first.indexed == 3
    assert first.failed == 0
    assert len(vector_store.search([1.0] * 8, limit=10)) == 3

    second = indexer.run()
    assert second.indexed == 0
    assert second.skipped == 3

    (documents_root / "faq.txt").write_text(
        "Regra atualizada.",
        encoding="utf-8",
    )
    (documents_root / "manual.md").unlink()

    third = indexer.run()

    assert third.indexed == 1
    assert third.deleted == 1
    manifest = ManifestStore(manifest_path).load()
    assert set(manifest.documents) == {"faq.txt", "manual.pdf"}
    assert manifest.documents["faq.txt"].status is IndexStatus.INDEXED


def test_ingestion_components_cover_validation_and_persistence_edges(
    integration_tmp_path: Path,
) -> None:
    tmp_path = integration_tmp_path
    registry = create_default_registry()
    text_path = tmp_path / "document.txt"
    text_path.write_text("texto", encoding="utf-8")

    loaded = registry.read(text_path, doc_id="document.txt")
    assert loaded.parts[0].text == "texto"
    assert registry.reader_for(text_path).supports(text_path)

    with pytest.raises(UnsupportedFileTypeError):
        registry.reader_for(tmp_path / "document.csv")
    with pytest.raises(DocumentReaderError):
        registry.read(tmp_path / "missing.txt", doc_id="missing.txt")
    with pytest.raises(DocumentReaderError):
        registry.read(tmp_path, doc_id="directory")

    document = DocumentLoaded(
        doc_id="doc-1",
        source_name="doc.txt",
        file_type=".txt",
        parts=(
            DocumentPart(index=0, text="  linha 1\r\n\r\n\r\nlinha 2  "),
            DocumentPart(index=1, text="   "),
        ),
    )
    normalized = DocumentNormalizer().normalize(document)
    assert normalized.parts[0].text == "linha 1\n\nlinha 2"
    assert len(RecursiveCharacterChunker().chunk(normalized)) == 1

    with pytest.raises(ValueError):
        RecursiveCharacterChunker(ChunkingConfig(max_chars=0))
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(ChunkingConfig(max_chars=10, overlap_chars=10))

    provider = GoogleEmbeddingProvider(DeterministicEmbeddings())
    assert provider.embed_documents([]) == []
    assert len(provider.embed_query("consulta")) == 8
    with pytest.raises(ValueError):
        provider.embed_query(" ")

    class InvalidEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0], [1.0, 2.0]]

        def embed_query(self, text: str) -> list[float]:
            return [1.0]

    with pytest.raises(RuntimeError, match="dimensões diferentes"):
        GoogleEmbeddingProvider(InvalidEmbeddings()).embed_documents(
            [Chunk(doc_id="doc-1", chunk_index=0, text="texto")]
        )

    manifest_path = tmp_path / "manifest.json"
    store = ManifestStore(manifest_path)
    assert store.load().documents == {}
    store.save(store.load())
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["documents"] == {}

    manifest_path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Failed to load manifest"):
        store.load()


def test_qdrant_store_validates_vectors_and_handles_empty_collection() -> None:
    store = QdrantStore(
        qdrant_client=QdrantClient(":memory:"),
        collection_name="empty_collection",
    )

    store.delete_by_document("missing")
    with pytest.raises(ValueError, match="chunks não corresponde"):
        store.replace_document(
            doc_id="doc-1",
            source_hash="hash-1",
            pipeline_version="v1",
            chunks=[Chunk(doc_id="doc-1", chunk_index=0, text="texto")],
            vectors=[],
        )
    with pytest.raises(ValueError, match="vetor não pode ser zero"):
        store.replace_document(
            doc_id="doc-1",
            source_hash="hash-1",
            pipeline_version="v1",
            chunks=[Chunk(doc_id="doc-1", chunk_index=0, text="texto")],
            vectors=[[]],
        )


def test_embedding_provider_wraps_model_failures() -> None:
    class FailingEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("provider failure")

        def embed_query(self, text: str) -> list[float]:
            return [1.0]

    with pytest.raises(RuntimeError, match="Falha ao gerar embeddings"):
        GoogleEmbeddingProvider(FailingEmbeddings()).embed_documents(
            [Chunk(doc_id="doc-1", chunk_index=0, text="texto")]
        )
