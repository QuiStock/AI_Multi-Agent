from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from src.agents.faq.models import DocumentLoaded


class DocumentReaderError(RuntimeError):
    """Erro durante a leitura de um documento."""


class UnsupportedFileTypeError(DocumentReaderError):
    """Extensão sem reader registrado."""


class DocumentReader(ABC):
    supported_extensions: ClassVar[frozenset[str]] = frozenset()

    def supports(self, file_path: Path) -> bool:
        """Check if the reader supports the given file path."""
        return file_path.suffix.lower() in self.supported_extensions

    def validate_path(self, path: Path) -> None:
        """Validate the given file path."""
        if not path.exists():
            raise DocumentReaderError(
                f"Arquivo não encontrado: {path}"
            )   

        if not path.is_file():
            raise DocumentReaderError(
                f"O caminho não é um arquivo: {path}"
            )

    @abstractmethod
    def read(self, path: Path, *, doc_id: str) -> DocumentLoaded:
        """Read a document and return its loaded representation."""
        raise NotImplementedError("Subclasses must implement the read method.")
