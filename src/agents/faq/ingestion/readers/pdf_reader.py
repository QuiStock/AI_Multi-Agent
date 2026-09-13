from pathlib import Path

from pypdf import PdfReader

from src.agents.faq.models import DocumentLoaded, DocumentPart

from .base_reader import DocumentReader, DocumentReaderError


class PDFReader(DocumentReader):
    supported_extensions = frozenset({".pdf"})

    def read(self, path: Path, *, doc_id: str) -> DocumentLoaded:
        """Read the PDF file and return its loaded representation."""
        self.validate_path(path)

        try:
            pdf = PdfReader(str(path))
        except Exception as e:
            raise DocumentReaderError(
                f"Erro ao ler o arquivo PDF {path}: {e}"
            ) from e

        parts: list[DocumentPart] = []
        for page_index, page in enumerate(pdf.pages):
            try:
                text = page.extract_text() or ""
            except Exception as e:
                raise DocumentReaderError(
                    "Erro ao extrair texto da página "
                    f"{page_index} do arquivo PDF {path}: {e}"
                ) from e

            parts.append(
                DocumentPart(
                    index=page_index, 
                    text=text,
                    page_number=page_index + 1,
                    metadata={
                        "text_extraction_empty": not bool(text.strip())
                    },
                    ))

        return DocumentLoaded(
            doc_id=doc_id,
            source_name=path.name,
            file_type=path.suffix.lower(),
            parts=tuple(parts),
        )
