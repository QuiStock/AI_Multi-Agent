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


def _build_loader(path: Path) -> BaseLoader:
    if path.suffix.lower() == ".pdf":
        return PyPDFLoader(str(path))
    return TextLoader(str(path), encoding="utf-8")


def load_documents(docs_dir: Path = config.FAQ_DOCS_DIR) -> list[Document]:
    documents: list[Document] = []
    for path in sorted(docs_dir.iterdir()):
        if path.is_file():
            documents.extend(_build_loader(path).load())
    return documents


def fingerprint_documents(docs_dir: Path = config.FAQ_DOCS_DIR) -> str:
    digest = hashlib.sha256()
    for path in sorted(docs_dir.rglob("*")):
        if path.is_file():
            digest.update(path.name.encode())
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


def _format_sources(
    vectorstore: FAISS, query: str, k: int = config.FAQ_RETRIEVAL_K
) -> str:
    documents = vectorstore.similarity_search(query, k=k)
    return "\n\n".join(
        f"[{document.metadata.get('source', 'desconhecido')}]\n{document.page_content}"
        for document in documents
    )


@tool
def faq_search(query: str) -> str:
    """Pesquisa a base de conhecimento do FAQ e retorna os trechos mais
    relevantes para a pergunta do usuário. Use SEMPRE que a dúvida envolver
    regras, políticas, processos ou informações documentadas."""
    vectorstore = ensure_index()
    if vectorstore is None:
        return "Nenhum documento disponível na base de conhecimento."
    return _format_sources(vectorstore, query)
