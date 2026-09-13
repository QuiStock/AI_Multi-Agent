from pathlib import Path

from src.agents.faq.models import DocumentLoaded, DocumentPart

from .base_reader import DocumentReader, DocumentReaderError


class TextReader(DocumentReader):
    """A reader for text files."""

    supported_extensions = frozenset({".txt"})

    def __init__(self, encoding: str = "utf-8-sig"):
        self.encoding = encoding


    def read(self, path: Path, *, doc_id: str) -> DocumentLoaded:
        """Read the text file and return its loaded representation."""
        self.validate_path(path)

        try:
            with path.open("r", encoding=self.encoding) as file:
                text = file.read()
        except Exception as e:
            raise DocumentReaderError(
                f"Erro ao ler o arquivo {path}: {e}"
            ) from e

        # Create a single DocumentPart for the entire text
        part = DocumentPart(
            index=0, 
            text=text
            )
        
        return DocumentLoaded(
            doc_id=doc_id,
            source_name=path.name, 
            file_type=path.suffix.lower(), 
            parts=(part,),
            )
