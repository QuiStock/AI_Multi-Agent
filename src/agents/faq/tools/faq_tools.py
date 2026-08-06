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


def _build_loader(path: Path) -> BaseLoader:
    if path.suffix.lower() == ".pdf":
        return PyPDFLoader(str(path))
    return TextLoader(str(path), encoding="utf-8")


def load_documents(docs_dir: Path = config.FAQ_DOCS_DIR) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative_source = path.relative_to(docs_dir).as_posix()
        for document in _build_loader(path).load():
            document.metadata["source"] = relative_source
            documents.append(document)
    return documents


def fingerprint_documents(docs_dir: Path = config.FAQ_DOCS_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(docs_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            digest.update(path.relative_to(docs_dir).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_metadata(metadata_file: Path = config.FAQ_METADATA_FILE) -> dict[str, Any]:
    if not metadata_file.exists():
        return {}
    data = json.loads(metadata_file.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _write_metadata(
    fingerprint: str, metadata_file: Path = config.FAQ_METADATA_FILE
) -> None:
    payload = {
        "docs_fingerprint": fingerprint,
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
    if embeddings is None:
        embeddings = get_embeddings()

    current_fingerprint = fingerprint_documents(docs_dir)
    metadata = _read_metadata(metadata_file)
    index_file = vectorstore_dir / "index.faiss"

    if current_fingerprint == metadata.get("docs_fingerprint") and index_file.exists():
        return FAISS.load_local(
            str(vectorstore_dir),
            embeddings,
            allow_dangerous_deserialization=True,
        )

    documents = load_documents(docs_dir)
    if not documents:
        return None

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.FAQ_CHUNK_SIZE,
        chunk_overlap=config.FAQ_CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)
    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(str(vectorstore_dir))
    _write_metadata(current_fingerprint, metadata_file)
    return vectorstore


def _relevance_from_distance(distance: float) -> float:
    """Converte a distância L2 do FAISS em uma escala de relevância (0 a 1)."""
    return 1 / (1 + distance)


def _format_sources(
    vectorstore: FAISS,
    query: str,
    k: int = config.FAQ_RETRIEVAL_K,
    min_relevance: float = config.FAQ_RETRIEVAL_MIN_RELEVANCE,
) -> str:
    matches = vectorstore.similarity_search_with_score(query, k=k)
    results = []
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
    """Pesquisa a base de conhecimento do FAQ e retorna os trechos mais
    relevantes para a pergunta do usuário. Use SEMPRE que a dúvida envolver
    regras, políticas, processos ou informações documentadas."""
    vectorstore = ensure_index()
    if vectorstore is None:
        return "Nenhum documento disponível na base de conhecimento."
    return _format_sources(vectorstore, query)
