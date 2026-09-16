from pathlib import Path

from src.agents.faq.models import DocumentLoaded, DocumentPart

from .base_reader import DocumentReader, DocumentReaderError


class MarkdownReader(DocumentReader):
    """A reader for Markdown files."""

    supported_extensions = frozenset({".md"})

    def read(self, path: Path, *, doc_id: str) -> DocumentLoaded:
        """Read the Markdown file and return its loaded representation."""
        self.validate_path(path)

        try:
            with path.open("r", encoding="utf-8") as file:
                text = file.read()
        except Exception as e:
            raise DocumentReaderError(f"Erro ao ler o arquivo {path}: {e}") from e

        # Create a single DocumentPart for the entire Markdown content
        part = DocumentPart(
            index=0,
            text=text,
        )

        return DocumentLoaded(
            doc_id=doc_id,
            source_name=path.name,
            file_type=path.suffix.lower(),
            parts=(part,),
        )
