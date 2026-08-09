import json
from pathlib import Path
from typing import Any

import pytest

from src.agents.faq.tools.faq_tool import (
    _read_metadata,
    fingerprint_documents,
    load_documents,
)

pytestmark = pytest.mark.integration


def test_build_index_end_to_end(pipeline: Any, docs_dir: Path) -> None:
    documents = load_documents(docs_dir)
    assert len(documents) >= 2

    store = pipeline.ensure(docs_dir)
    assert store is not None
    assert (docs_dir.parent / "vectorstore" / "index.faiss").exists()
    assert (docs_dir.parent / "metadata.json").exists()

    metadata_path = docs_dir.parent / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["docs_fingerprint"] == fingerprint_documents(docs_dir)

    hits = store.similarity_search("regra de negocio", k=4)
    assert len(hits) >= 1
    assert hits[0].page_content.strip()


def test_index_reuses_existing_when_unchanged(
    pipeline: Any, docs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = pipeline.ensure(docs_dir)
    assert first is not None
    metadata_path = docs_dir.parent / "metadata.json"
    metadata_before = metadata_path.read_text(encoding="utf-8")

    def fail_load(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("nao deveria recarregar documentos")

    monkeypatch.setattr("src.agents.faq.tools.faq_tool.load_documents", fail_load)

    second = pipeline.ensure(docs_dir)
    assert second is not None
    metadata_after = metadata_path.read_text(encoding="utf-8")
    assert metadata_before == metadata_after


def test_index_rebuilds_when_docs_change(pipeline: Any, docs_dir: Path) -> None:
    pipeline.ensure(docs_dir)

    (docs_dir / "doc.txt").write_text(
        "Conteudo alterado do documento.", encoding="utf-8"
    )
    store = pipeline.ensure(docs_dir)
    assert store is not None

    metadata_path = docs_dir.parent / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["docs_fingerprint"] == fingerprint_documents(docs_dir)


def test_index_returns_none_without_documents(pipeline: Any, tmp_path: Path) -> None:
    empty_dir = tmp_path / "vazio"
    empty_dir.mkdir()
    assert pipeline.ensure(empty_dir) is None


def test_read_metadata_ignores_malformed_content(tmp_path: Path) -> None:
    metadata_file = tmp_path / "metadata.json"
    metadata_file.write_text("[]", encoding="utf-8")
    assert _read_metadata(metadata_file) == {}


def test_faq_search_end_to_end(pipeline: Any, docs_dir: Path) -> None:
    result = pipeline.search("qual a regra de negocio do FAQ?", docs_dir)
    assert "doc.txt" in result
    assert "manual.pdf" in result
    assert "Regra de negocio" in result
    assert "Regra em PDF." in result


def test_faq_search_no_documents(pipeline: Any, tmp_path: Path) -> None:
    empty_dir = tmp_path / "vazio"
    empty_dir.mkdir()
    result = pipeline.search("qual a regra?", empty_dir)
    assert result == "Nenhum documento disponível na base de conhecimento."
