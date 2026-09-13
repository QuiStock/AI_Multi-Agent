import logging
from time import perf_counter
from typing import Any

from src.agents.faq.ingestion.embedding.google_embedding_provider import (
    GoogleEmbeddingProvider,
)
from src.agents.faq.ingestion.vectorstore.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


class QdrantRetriever:
    def __init__(
        self,
        embedding_provider: GoogleEmbeddingProvider,
        vector_store: QdrantStore,
        top_k: int = 4,
        min_score: float = 0.3,
    ):
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.top_k = top_k
        self.min_score = min_score

    def search(self, query: str) -> list[dict[str, Any]]:
        started_at = perf_counter()
        candidates_count = 0
        results_count = 0

        try:

            query_vector = self.embedding_provider.embed_query(query)

            points = self.vector_store.search(
                query_vector=query_vector,
                limit=self.top_k,
            )
            candidates_count = len(points)

            evidences: list[dict[str, Any]] = []

            for point in points:
                if point.score < self.min_score:
                    continue

                payload = point.payload or {}

                evidences.append(
                    {
                        "arquivo": payload.get(
                            "source_name",
                            "desconhecido",
                        ),
                        "conteudo": payload.get("text", ""),
                        "relevancia": round(point.score, 4),
                        "pagina": payload.get("page_number"),
                    }
                )

            results_count = len(evidences)
            return evidences
        except Exception:
            logger.exception("faq_retrieval_failed")
            raise

        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.info(
                "faq_retrieval_finished",
                extra={
                    "candidates_count": candidates_count,
                    "results_count": results_count,
                    "no_results": results_count == 0,
                    "duration_ms": duration_ms,
                },
            )
