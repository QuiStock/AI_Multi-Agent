# rag/models.py

from dataclasses import dataclass, field
from enum import Enum


class IndexStatus(str, Enum):
    INDEXED = "indexed"
    FAILED = "failed"


@dataclass(frozen=True)
class IndexedDocumentState:
    doc_id: str
    source_hash: str
    pipeline_version: str
    chunk_count: int
    status: IndexStatus
    indexed_at: str | None = None
    error: str | None = None


@dataclass
class Manifest:
    schema_version: int = 1
    documents: dict[str, IndexedDocumentState] = field(default_factory=dict)
