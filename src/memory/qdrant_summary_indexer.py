"""Qdrant index for conversation summaries."""

from collections.abc import Callable, Sequence
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from .contracts import ConversationSummarySnapshot


class QdrantSummaryIndexer:
    def __init__(
        self,
        *,
        client: QdrantClient,
        embed_text: Callable[[str], Sequence[float]],
        collection_name: str,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("collection_name é obrigatório")
        self._client = client
        self._embed_text = embed_text
        self._collection_name = collection_name

    def upsert(self, snapshot: ConversationSummarySnapshot) -> None:
        if snapshot.status != "ended":
            raise ValueError("Apenas conversas encerradas podem ser indexadas")
        if not snapshot.summary or not snapshot.summary.strip():
            raise ValueError("A conversa precisa de resumo antes da indexação")

        vector = list(self._embed_text(snapshot.summary))
        if not vector:
            raise ValueError("O embedding do resumo não pode estar vazio")

        self._ensure_collection(vector_size=len(vector))
        self._client.upsert(
            collection_name=self._collection_name,
            points=[
                models.PointStruct(
                    id=self._point_id(snapshot.conversation_id),
                    vector=vector,
                    payload={
                        "memory_type": "conversation_summary",
                        "user_id": snapshot.user_id,
                        "conversation_id": snapshot.conversation_id,
                        "status": snapshot.status,
                        "title": snapshot.title,
                        "summary": snapshot.summary,
                        "summary_version": snapshot.summary_version,
                        "updated_at": snapshot.updated_at.isoformat(),
                    },
                )
            ],
            wait=True,
        )

    def _ensure_collection(self, *, vector_size: int) -> None:
        if self._client.collection_exists(self._collection_name):
            return
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    def _point_id(self, conversation_id: str) -> str:
        value = f"{self._collection_name}:{conversation_id}"
        return str(uuid5(NAMESPACE_URL, value))
