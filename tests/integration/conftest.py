from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import Embeddings

TXT_CONTENT = "Regra de negocio do FAQ da instituicao."


class FakeEmbeddings(Embeddings):
    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [float(byte) / 255.0 for byte in digest[:8]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def make_pdf(path: Path) -> None:
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


class PipelineHarness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.agents.faq.tools import faq_tools

        self._faq_tools = faq_tools
        self._monkeypatch = monkeypatch
        self._vectorstore_dir = tmp_path / "vectorstore"
        self._metadata_file = tmp_path / "metadata.json"

    def ensure(self, docs: Path, embeddings: Any | None = None) -> Any:
        if embeddings is None:
            embeddings = FakeEmbeddings()
        return self._faq_tools.ensure_index(
            embeddings,
            docs_dir=docs,
            vectorstore_dir=self._vectorstore_dir,
            metadata_file=self._metadata_file,
        )

    def point_to(self, docs: Path) -> None:
        original = self._faq_tools.ensure_index

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("docs_dir", docs)
            kwargs.setdefault("vectorstore_dir", self._vectorstore_dir)
            kwargs.setdefault("metadata_file", self._metadata_file)
            return original(*args, **kwargs)

        self._monkeypatch.setattr(self._faq_tools, "ensure_index", wrapped)

    def search(self, query: str, docs: Path) -> str:
        self._monkeypatch.setattr(
            self._faq_tools, "get_embeddings", lambda: FakeEmbeddings()
        )
        self.point_to(docs)
        return self._faq_tools.faq_search.invoke({"query": query})


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PipelineHarness:
    return PipelineHarness(tmp_path, monkeypatch)


@pytest.fixture
def docs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "docs"
    directory.mkdir()
    (directory / "doc.txt").write_text(TXT_CONTENT, encoding="utf-8")
    make_pdf(directory / "manual.pdf")
    return directory
