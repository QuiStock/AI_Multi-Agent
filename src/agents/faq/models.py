from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentPart:
    """A part of a document, typically a chunk of text with associated metadata."""

    index: int
    text: str
    page_number: int | None = None
    heading: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentLoaded:
    """A document that has been loaded and split into parts."""

    doc_id: str
    source_name: str
    file_type: str
    parts: tuple[DocumentPart, ...]
