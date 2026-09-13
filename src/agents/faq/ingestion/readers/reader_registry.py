from pathlib import Path

from src.agents.faq.models import DocumentLoaded

from .base_reader import (
    DocumentReader,
    UnsupportedFileTypeError,
)
from .markdown_reader import MarkdownReader
from .pdf_reader import PDFReader
from .text_reader import TextReader


class ReaderRegistry:
    """Registry for document readers."""

    def __init__(self, readers: list[DocumentReader]):
        self._reader_by_extension: dict[str, DocumentReader] = {}

        for reader in readers:
            for ext in reader.supported_extensions:
                normalized_extension = ext.lower()

                if normalized_extension in self._reader_by_extension:
                    raise ValueError(
                        f"Existe mais de um reader para "
                        f"{normalized_extension}"
                    )

                self._reader_by_extension[normalized_extension] = reader

    def reader_for(self, file_path: Path) -> DocumentReader:
        """Get the appropriate reader for the given file path."""
        extension = file_path.suffix.lower()
        reader = self._reader_by_extension.get(extension)

        if reader is None:
            raise UnsupportedFileTypeError(
                f"Não há reader registrado para a extensão {extension}"
            )

        return reader

    def read(self, path: Path, *, doc_id: str) -> DocumentLoaded:
        """Read a document using the reader registered for its extension."""
        reader = self.reader_for(path)
        return reader.read(path, doc_id=doc_id)

def create_default_registry() -> ReaderRegistry:
    return ReaderRegistry(
        readers=[
            TextReader(),
            MarkdownReader(),
            PDFReader(),
        ]
    )
