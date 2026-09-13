import logging
from collections.abc import Sequence
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from src.agents.faq.ingestion.processing.models import Chunk

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(
        self,
        qdrant_client: QdrantClient,
        collection_name: str,
    ):
        self.qdrant_client = qdrant_client
        self.collection_name = collection_name


    def ensure_collection(
            self,
            vector_size: int,
    ) -> None:
        if self.qdrant_client.collection_exists(self.collection_name):
            return

        self.qdrant_client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    def replace_document(
            self,
            *,
            doc_id: str,
            source_hash: str,
            pipeline_version: str,
            chunks: Sequence[Chunk],
            vectors: Sequence[Sequence[float]],
    )-> None:
        if len(chunks) != len(vectors):
            raise ValueError(
                "O número de chunks não corresponde ao número de vetores."
            )
        
        if not chunks:
            self.delete_by_document(doc_id=doc_id)
            return

        vector_size = len(vectors[0])

        if vector_size == 0:
            raise ValueError("O tamanho do vetor não pode ser zero.")

        self.ensure_collection(vector_size=vector_size)

        points: list[models.PointStruct] = []

        for chunk, vector in zip(chunks, vectors, strict=True):
            point_id = self._point_id(
                doc_id=doc_id,
                source_hash=source_hash,
                chunk_index=chunk.chunk_index,
            )

            payload = {
                "doc_id": doc_id,
                "source_hash": source_hash,
                "pipeline_version": pipeline_version,
                "source_name": chunk.metadata.get(
                    "source_name"
                ),
                "file_type": chunk.metadata.get(
                    "file_type"
                ),
                "part_index": chunk.metadata.get(
                    "part_index"
                ),
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "heading": chunk.heading,
            }

            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=list(vector),
                    payload=payload,
                )
            )

        started_at = perf_counter()
        points_inserted = len(points)


        try:
            # Salva a nova versão.
            self.qdrant_client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )

            self.delete_old_versions(
                doc_id=doc_id,
                source_hash=source_hash,
            )

            logger.info(
                "qdrant_document_replaced",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "points_inserted": points_inserted,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
        except Exception:
            logger.exception(
                "qdrant_document_replace_failed",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "points_inserted": points_inserted,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            raise

    def delete_by_document(
        self,
        doc_id: str,
    ) -> None:
        if not self.qdrant_client.collection_exists(
            self.collection_name
        ):
            logger.info(
                "qdrant_document_deleted",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "points_removed": 0,
                    "duration_ms": 0.0,
                },
            )
            return

        started_at = perf_counter()

        document_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchValue(
                        value=doc_id
                    ),
                )
            ]
        )

        try:
            points_removed = self._count_points(document_filter)

            self.qdrant_client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=document_filter
                ),
                wait=True,
            )

            logger.info(
                "qdrant_document_deleted",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "points_removed": points_removed,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
        except Exception:
            logger.exception(
                "qdrant_document_delete_failed",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            raise

    def delete_old_versions(
        self,
        *,
        doc_id: str,
        source_hash: str,
    ) -> None:
        old_version_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchValue(
                        value=doc_id
                    ),
                )
            ],
            must_not=[
                models.FieldCondition(
                    key="source_hash",
                    match=models.MatchValue(
                        value=source_hash
                    ),
                )
            ],
        )

        started_at = perf_counter()

        try:
            points_removed = self._count_points(old_version_filter)

            self.qdrant_client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=old_version_filter
                ),
                wait=True,
            )

            logger.info(
                "qdrant_old_versions_deleted",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "points_removed": points_removed,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
        except Exception:
            logger.exception(
                "qdrant_old_versions_delete_failed",
                extra={
                    "collection_name": self.collection_name,
                    "doc_id": doc_id,
                    "duration_ms": round(
                        (perf_counter() - started_at) * 1000,
                        2,
                    ),
                },
            )
            raise

    def search(
        self,
        query_vector: Sequence[float],
        limit: int = 4,
    ):
        result = self.qdrant_client.query_points(
            collection_name=self.collection_name,
            query=list(query_vector),
            limit=limit,
            with_payload=True,
        )

        return result.points

    def _point_id(
        self,
        *,
        doc_id: str,
        source_hash: str,
        chunk_index: int,
    ) -> str:
        value = (
            f"{self.collection_name}:"
            f"{doc_id}:"
            f"{source_hash}:"
            f"{chunk_index}"
        )

        return str(
            uuid5(NAMESPACE_URL, value)
        )

    def _count_points(self, point_filter: models.Filter) -> int:
        result = self.qdrant_client.count(
            collection_name=self.collection_name,
            count_filter=point_filter,
            exact=True,
        )
        return int(result.count)
