import logging
from collections.abc import Sequence
from time import perf_counter

from langchain_core.embeddings import Embeddings

from src.agents.faq.ingestion.processing.models import Chunk
from src.llm_factory import embeddings

logger = logging.getLogger(__name__)


class GoogleEmbeddingProvider:
    """
    Adapter entre o pipeline de ingestão e o modelo de embeddings do Google.
    """

    def __init__(
        self,
        embedding_model: Embeddings | None = None,
    ):
        self._embedding_model = (
            embedding_model or embeddings
        )

    @property
    def model_name(self) -> str:
        return str(
            getattr(
                self._embedding_model,
                "model",
                "google-embedding",
            )
        )

    def embed_documents(
        self,
        chunks: Sequence[Chunk],
    ) -> list[list[float]]:
        started_at = perf_counter()
        chunk_count = len(chunks)

        logger.info(
            "faq_embedding_documents_started",
            extra={
                "model_name": self.model_name,
                "chunk_count": chunk_count,
            },
        )

        if not chunks:
            logger.info(
                "faq_embeddings_finished",
                extra={
                    "chunk_count": 0,
                    "embedding_count": 0,
                    "vector_dimension": 0,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            return []

        texts = [
            chunk.text
            for chunk in chunks
        ]

        try:
            vectors = self._embedding_model.embed_documents(texts)

            self._validate_dimensions(vectors)

            dimension = len(vectors[0]) if vectors else 0

            logger.info(
                "faq_embeddings_finished",
                extra={
                    "chunk_count": chunk_count,
                    "embedding_count": len(vectors),
                    "vector_dimension": dimension,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )

            return [
                [float(value) for value in vector]
                for vector in vectors
            ]
        except Exception as exc:
            logger.exception(
                "faq_embedding_documents_failed",
                extra={
                    "model_name": self.model_name,
                    "chunk_count": chunk_count,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            raise RuntimeError(
                f"Falha ao gerar embeddings para {chunk_count} chunks: {exc}"
            ) from exc

    def embed_query(
        self,
        query: str,
    ) -> list[float]:
        if not query.strip():
            raise ValueError(
                "A consulta não pode estar vazia."
            )

        vector = self._embedding_model.embed_query(
            query
        )

        return [
            float(value)
            for value in vector
        ]

    @staticmethod
    def _validate_dimensions(
        vectors: list[list[float]],
    ) -> None:
        if not vectors:
            return

        dimension = len(vectors[0])

        if dimension == 0:
            raise RuntimeError(
                "O embedding retornou um vetor vazio."
            )

        invalid_vectors = [
            vector
            for vector in vectors
            if len(vector) != dimension
        ]

        if invalid_vectors:
            raise RuntimeError(
                "Os embeddings retornaram dimensões diferentes."
            )
