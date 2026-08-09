from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config
from src.models import get_embeddings

SUPPORTED_EXTENSIONS = frozenset({".md", ".pdf", ".txt"})


def _build_loader(file_path: Path) -> BaseLoader:
    """Build the appropriate loader for a supported file."""
    if file_path.suffix.lower() == ".pdf":
        return PyPDFLoader(str(file_path))
    return TextLoader(str(file_path), encoding="utf-8")


def load_documents(documents_dir: Path = config.FAQ_DOCS_DIR) -> list[Document]:
    """Load supported documents recursively and preserve their source metadata."""
    documents: list[Document] = []
    for file_path in sorted(documents_dir.rglob("*")):
        if (
            not file_path.is_file()
            or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS
        ):
            continue

        relative_source = file_path.relative_to(documents_dir).as_posix()
        for document in _build_loader(file_path).load():
            document.metadata["source"] = relative_source
            documents.append(document)
    return documents


def fingerprint_documents(documents_dir: Path = config.FAQ_DOCS_DIR) -> str:
    """Return a deterministic fingerprint for all supported documents."""
    digest = hashlib.sha256()
    for file_path in sorted(documents_dir.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            digest.update(file_path.relative_to(documents_dir).as_posix().encode())
            digest.update(file_path.read_bytes())
    return digest.hexdigest()


def _read_metadata(metadata_file: Path = config.FAQ_METADATA_FILE) -> dict[str, Any]:
    """Read index metadata or return an empty mapping when it is unavailable."""
    if not metadata_file.exists():
        return {}
    data = json.loads(metadata_file.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_metadata(
    docs_fingerprint: str, metadata_file: Path = config.FAQ_METADATA_FILE
) -> None:
    """Persist the document fingerprint and the index creation timestamp."""
    payload = {
        "docs_fingerprint": docs_fingerprint,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_index(
    embeddings: GoogleGenerativeAIEmbeddings | None = None,
    *,
    docs_dir: Path = config.FAQ_DOCS_DIR,
    vectorstore_dir: Path = config.FAQ_VECTORSTORE_DIR,
    metadata_file: Path = config.FAQ_METADATA_FILE,
) -> FAISS | None:
    """Load a valid local index or build one when the documents have changed."""
    if embeddings is None:
        embeddings = get_embeddings()

    current_fingerprint = fingerprint_documents(docs_dir)
    metadata = _read_metadata(metadata_file)
    index_file = vectorstore_dir / "index.faiss"
    index_metadata_file = vectorstore_dir / "index.pkl"

    if (
        current_fingerprint == metadata.get("docs_fingerprint")
        and index_file.exists()
        and index_metadata_file.exists()
    ):
        return FAISS.load_local(
            str(vectorstore_dir),
            embeddings,
            allow_dangerous_deserialization=True,
        )

    documents = load_documents(docs_dir)
    if not documents:
        return None

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.FAQ_CHUNK_SIZE,
        chunk_overlap=config.FAQ_CHUNK_OVERLAP,
    )
    chunks = text_splitter.split_documents(documents)
    vector_store = FAISS.from_documents(chunks, embeddings)
    vectorstore_dir.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(str(vectorstore_dir))
    _write_metadata(current_fingerprint, metadata_file)
    return vector_store


def _relevance_from_distance(distance: float) -> float:
    """Convert a non-negative FAISS distance into a bounded relevance score."""
    return 1 / (1 + distance) if distance >= 0 else 0.0


def _format_sources(
    vector_store: FAISS,
    query: str,
    k: int = config.FAQ_RETRIEVAL_K,
    min_relevance: float = config.FAQ_RETRIEVAL_MIN_RELEVANCE,
) -> str:
    """Retrieve, filter, and serialize evidence for the FAQ agent."""
    matches = vector_store.similarity_search_with_score(query, k=k)
    results: list[dict[str, Any]] = []

    for document, distance in matches:
        relevance = _relevance_from_distance(float(distance))
        if relevance < min_relevance:
            continue

        result: dict[str, Any] = {
            "arquivo": document.metadata.get("source", "desconhecido"),
            "relevancia": round(relevance, 4),
            "conteudo": document.page_content,
        }
        if "page" in document.metadata:
            result["pagina"] = int(document.metadata["page"]) + 1
        results.append(result)

    if not results:
        return "Nenhuma evidência relevante encontrada na base de conhecimento."
    return json.dumps({"resultados": results}, ensure_ascii=False)


@tool
def faq_search(query: str) -> str:
    """Search the FAQ knowledge base and return relevant evidence excerpts.

    Use this tool whenever the user asks about documented rules, policies,
    processes, or institutional information. Answers must be based only on the
    returned excerpts and should cite their source files.
    """
    vector_store = ensure_index()
    if vector_store is None:
        return "Nenhum documento disponível na base de conhecimento."
    return _format_sources(vector_store, query)
