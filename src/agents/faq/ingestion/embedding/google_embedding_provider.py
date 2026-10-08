import logging
from collections.abc import Mapping, Sequence
from time import perf_counter
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.agents.faq.ingestion.processing.models import Chunk
from src.llm_factory import embeddings
from src.observability.ai_usage_repository import (
    MongoAIUsageRepository,
    UsageSource,
    UsageStatus,
    record_usage_safely,
)

logger = logging.getLogger(__name__)


class GoogleEmbeddingProvider:
    """
    Adapter entre o pipeline de ingestão e o modelo de embeddings do Google.
    """

    def __init__(
        self,
        embedding_model: Embeddings | None = None,
        *,
        usage_repository: MongoAIUsageRepository | None = None,
    ):
        self._embedding_model = embedding_model or embeddings
        self._usage_repository = usage_repository

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
        *,
        source: UsageSource = "faq_embedding_index",
        conversation_id: str | None = None,
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

        texts = [chunk.text for chunk in chunks]

        try:
            if isinstance(self._embedding_model, GoogleGenerativeAIEmbeddings):
                vectors = self._embed_google_documents(
                    texts,
                    source=source,
                    conversation_id=conversation_id,
                )
            else:
                vectors = self._embedding_model.embed_documents(texts)
                self._record_usage(
                    source=source,
                    input_tokens=None,
                    item_count=len(texts),
                    conversation_id=conversation_id,
                )

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

            return [[float(value) for value in vector] for vector in vectors]
        except Exception as exc:
            self._record_usage(
                source=source,
                input_tokens=None,
                item_count=chunk_count,
                status="error",
                conversation_id=conversation_id,
            )
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
        *,
        source: UsageSource = "memory_embedding_query",
        conversation_id: str | None = None,
    ) -> list[float]:
        if not query.strip():
            raise ValueError("A consulta não pode estar vazia.")

        try:
            if isinstance(self._embedding_model, GoogleGenerativeAIEmbeddings):
                response = self._embedding_model.client.models.embed_content(
                    model=self._embedding_model.model,
                    contents=query,
                    config=self._embedding_model._build_config(
                        task_type=(
                            self._embedding_model.task_type or "RETRIEVAL_QUERY"
                        ),
                        output_dimensionality=(
                            self._embedding_model.output_dimensionality
                        ),
                    ),
                )
                vector = list(response.embeddings[0].values)
                self._record_usage(
                    source=source,
                    input_tokens=self._usage_token_count(response),
                    item_count=1,
                    conversation_id=conversation_id,
                )
            else:
                vector = self._embedding_model.embed_query(query)
                self._record_usage(
                    source=source,
                    input_tokens=None,
                    item_count=1,
                    conversation_id=conversation_id,
                )
        except Exception:
            self._record_usage(
                source=source,
                input_tokens=None,
                item_count=1,
                status="error",
                conversation_id=conversation_id,
            )
            raise

        return [float(value) for value in vector]

    def _embed_google_documents(
        self,
        texts: list[str],
        *,
        source: UsageSource,
        conversation_id: str | None,
    ) -> list[list[float]]:
        model = self._embedding_model
        if not isinstance(model, GoogleGenerativeAIEmbeddings):
            raise TypeError("O modelo Google esperado não está configurado")

        vectors: list[list[float]] = []
        for batch in model._prepare_batches(texts, batch_size=100):
            response = model.client.models.embed_content(
                model=model.model,
                contents=[{"parts": [{"text": text}]} for text in batch],
                config=model._build_config(
                    task_type=model.task_type or "RETRIEVAL_DOCUMENT",
                    output_dimensionality=model.output_dimensionality,
                ),
            )
            vectors.extend(
                [list(embedding.values) for embedding in response.embeddings]
            )
            self._record_usage(
                source=source,
                input_tokens=self._usage_token_count(response),
                item_count=len(batch),
                conversation_id=conversation_id,
            )
        return vectors

    @staticmethod
    def _usage_token_count(response: object) -> int | None:
        usage = getattr(response, "usage_metadata", None)
        if isinstance(usage, Mapping):
            value = usage.get("prompt_token_count", usage.get("promptTokenCount"))
        else:
            value = getattr(usage, "prompt_token_count", None)
            if value is None:
                value = getattr(usage, "promptTokenCount", None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def _record_usage(
        self,
        *,
        source: UsageSource,
        input_tokens: int | None,
        item_count: int,
        status: UsageStatus = "completed",
        conversation_id: str | None = None,
    ) -> None:
        record_usage_safely(
            self._usage_repository,
            event_id=str(uuid4()),
            source=source,
            model=self.model_name,
            input_tokens=input_tokens,
            output_tokens=0,
            status=status,
            item_count=item_count,
            conversation_id=conversation_id,
        )

    @staticmethod
    def _validate_dimensions(
        vectors: list[list[float]],
    ) -> None:
        if not vectors:
            return

        dimension = len(vectors[0])

        if dimension == 0:
            raise RuntimeError("O embedding retornou um vetor vazio.")

        invalid_vectors = [vector for vector in vectors if len(vector) != dimension]

        if invalid_vectors:
            raise RuntimeError("Os embeddings retornaram dimensões diferentes.")
