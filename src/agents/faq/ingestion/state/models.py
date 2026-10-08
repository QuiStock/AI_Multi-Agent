# rag/models.py

from dataclasses import dataclass, field
from enum import Enum

from src.agents.faq.ingestion.audience import Audience


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
    audience: Audience | None = None
    indexed_at: str | None = None
    error: str | None = None


@dataclass
class Manifest:
    schema_version: int = 2
    audience_policy_version: str = "faq-audience-v1"
    documents: dict[str, IndexedDocumentState] = field(default_factory=dict)
