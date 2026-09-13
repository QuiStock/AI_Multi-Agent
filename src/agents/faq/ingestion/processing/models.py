from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """A chunk of text with associated metadata."""

    doc_id: str
    chunk_index: int
    text: str
    page_number: int | None = None
    heading: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 1_000
    overlap_chars: int = 150
