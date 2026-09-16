from abc import ABC, abstractmethod

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.agents.faq.ingestion.processing.models import Chunk, ChunkingConfig
from src.agents.faq.models import DocumentLoaded


class Chunker(ABC):
    @abstractmethod
    def chunk(self, document: DocumentLoaded) -> tuple[Chunk, ...]:
        """Split a loaded document into chunks."""
        raise NotImplementedError("Subclasses must implement the chunk method.")


class RecursiveCharacterChunker(Chunker):
    def __init__(
        self,
        config: ChunkingConfig | None = None,
    ):
        self.config = config or ChunkingConfig()

        if self.config.max_chars <= 0:
            raise ValueError("max_chars deve ser maior que zero")

        if self.config.overlap_chars < 0:
            raise ValueError("overlap_chars não pode ser negativo")

        if self.config.overlap_chars >= self.config.max_chars:
            raise ValueError("overlap_chars deve ser menor que max_chars")

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.max_chars,
            chunk_overlap=self.config.overlap_chars,
            separators=[
                "\n\n",
                "\n",
                " ",
                "",
            ],
            length_function=len,
            is_separator_regex=False,
        )

    def chunk(self, document: DocumentLoaded) -> tuple[Chunk, ...]:
        chunks: list[Chunk] = []
        chunk_index = 0

        for part in document.parts:
            text = part.text.strip()

            if not text:
                continue

            part_chunks = self.text_splitter.split_text(text)

            for chunk_text in part_chunks:
                chunks.append(
                    Chunk(
                        doc_id=document.doc_id,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        page_number=part.page_number,
                        heading=part.heading,
                        metadata={
                            "source_name": (document.source_name),
                            "file_type": document.file_type,
                            "part_index": part.index,
                            "chunk_size": (self.config.max_chars),
                            "chunk_overlap": (self.config.overlap_chars),
                        },
                    )
                )
                chunk_index += 1

        return tuple(chunks)
