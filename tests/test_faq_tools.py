import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document

from src.agents.faq.agent_card import create_faq_agent, faq_app
from src.agents.faq.tools.faq_tool import (
    _format_sources,
    ensure_index,
    faq_search,
    fingerprint_documents,
    load_documents,
)
from src.models import get_embeddings


class FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeVectorStore:
    def similarity_search_with_score(
        self, query: str, k: int = 4
    ) -> list[tuple[Document, float]]:
        return [
            (
                Document(
                    page_content="regra de negócio do FAQ",
                    metadata={"source": "doc.txt"},
                ),
                0.1,
            )
        ]


def _make_docs(tmp_path: Path) -> Path:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "doc.txt").write_text("Regra de negócio do FAQ.", encoding="utf-8")
    return docs_dir


def test_fingerprint_changes_when_doc_modified(tmp_path: Path) -> None:
    docs_dir = _make_docs(tmp_path)
    before = fingerprint_documents(docs_dir)
    (docs_dir / "doc.txt").write_text("Conteúdo alterado.", encoding="utf-8")
    after = fingerprint_documents(docs_dir)
    assert before != after


def test_ensure_index_builds_and_skips_rebuild_when_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs_dir = _make_docs(tmp_path)
    vstore = tmp_path / "vectorstore"
    meta = tmp_path / "metadata.json"

    first = ensure_index(
        FakeEmbeddings(),
        docs_dir=docs_dir,
        vectorstore_dir=vstore,
        metadata_file=meta,
    )
    assert first is not None
    assert (vstore / "index.faiss").exists()
    assert meta.exists()

    def fail_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("não deveria recarregar documentos")

        monkeypatch.setattr("src.agents.faq.tools.faq_tool.load_documents", fail_load)

    second = ensure_index(
        FakeEmbeddings(),
        docs_dir=docs_dir,
        vectorstore_dir=vstore,
        metadata_file=meta,
    )
    assert second is not None


def test_ensure_index_rebuilds_when_doc_changes(tmp_path: Path) -> None:
    docs_dir = _make_docs(tmp_path)
    vstore = tmp_path / "vectorstore"
    meta = tmp_path / "metadata.json"

    ensure_index(
        FakeEmbeddings(),
        docs_dir=docs_dir,
        vectorstore_dir=vstore,
        metadata_file=meta,
    )
    (docs_dir / "doc.txt").write_text("Conteúdo alterado.", encoding="utf-8")

    store = ensure_index(
        FakeEmbeddings(),
        docs_dir=docs_dir,
        vectorstore_dir=vstore,
        metadata_file=meta,
    )
    assert store is not None
    metadata = json.loads(meta.read_text(encoding="utf-8"))
    assert metadata["docs_fingerprint"] == fingerprint_documents(docs_dir)


def test_ensure_index_returns_none_without_documents(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    store = ensure_index(
        FakeEmbeddings(),
        docs_dir=docs_dir,
        vectorstore_dir=tmp_path / "vectorstore",
        metadata_file=tmp_path / "metadata.json",
    )
    assert store is None


def test_format_sources_includes_source() -> None:
    formatted = _format_sources(FakeVectorStore(), "qual a regra?")
    result = json.loads(formatted)
    assert result["resultados"][0]["arquivo"] == "doc.txt"
    assert result["resultados"][0]["relevancia"] > 0
    assert "regra de negócio do FAQ" in formatted


def test_format_sources_discards_low_relevance_results() -> None:
    class DistantVectorStore:
        def similarity_search_with_score(
            self, query: str, k: int = 4
        ) -> list[tuple[Document, float]]:
            return [(Document(page_content="irrelevante"), 100.0)]

    result = _format_sources(DistantVectorStore(), "qual a regra?")
    assert result == "Nenhuma evidência relevante encontrada na base de conhecimento."


def test_load_documents_loads_supported_files_recursively(tmp_path: Path) -> None:
    docs_dir = _make_docs(tmp_path)
    nested_dir = docs_dir / "subpasta"
    nested_dir.mkdir()
    (nested_dir / "manual.md").write_text("Conteúdo do manual.", encoding="utf-8")
    (docs_dir / "ignorar.csv").write_text("coluna", encoding="utf-8")

    documents = load_documents(docs_dir)

    assert {document.metadata["source"] for document in documents} == {
        "doc.txt",
        "subpasta/manual.md",
    }


def test_faq_search_returns_message_when_no_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.faq.tools.faq_tool.ensure_index",
        lambda *args: None,
    )
    result = faq_search.invoke({"query": "pergunta qualquer"})
    assert result == "Nenhum documento disponível na base de conhecimento."


def test_faq_search_returns_formatted_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.agents.faq.tools.faq_tool.ensure_index",
        lambda *args: FakeVectorStore(),
    )
    result = faq_search.invoke({"query": "qual a regra?"})
    assert json.loads(result)["resultados"][0]["arquivo"] == "doc.txt"


def test_faq_agent_is_created(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.config.GEMINI_API_KEY", "fake-key-for-test")
    agent = create_faq_agent()
    assert agent is not None


def test_get_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    embeddings = get_embeddings()
    assert embeddings.model == "models/gemini-embedding-001"


def test_faq_app_is_callable() -> None:
    assert callable(faq_app)
