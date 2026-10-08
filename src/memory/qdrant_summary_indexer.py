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
        if snapshot.summarized_through_message_id not in {
            message.message_id for message in snapshot.messages
        }:
            raise ValueError("O watermark precisa existir no array canônico messages")

        vector = list(self._embed_text(snapshot.summary))
        if not vector:
            raise ValueError("O embedding do resumo não pode estar vazio")

        self._ensure_collection(vector_size=len(vector))
        current = self.get(snapshot.conversation_id)
        message_positions = {
            message.message_id: index for index, message in enumerate(snapshot.messages)
        }
        current_marker = (
            current.get("summarized_through_message_id")
            if current is not None
            else None
        )
        if current is not None:
            if current_marker not in message_positions:
                raise ValueError(
                    "Watermark Qdrant ausente no histórico; reconciliação necessária"
                )
            new_position = message_positions[snapshot.summarized_through_message_id]
            if message_positions[current_marker] > new_position:
                return
            if message_positions[current_marker] == new_position:
                current_version = current.get("summary_version", 0)
                if (
                    isinstance(current_version, int)
                    and current_version >= snapshot.summary_version
                ):
                    return
        self._client.upsert(
            collection_name=self._collection_name,
            points=[
                models.PointStruct(
                    id=self._point_id(snapshot.conversation_id),
                    vector=vector,
                    payload={
                        "memory_type": "conversation_summary",
                        "email": snapshot.email,
                        "conversation_id": snapshot.conversation_id,
                        "status": snapshot.status,
                        "title": snapshot.title,
                        "summary": snapshot.summary,
                        "summary_version": snapshot.summary_version,
                        "summarized_through_message_id": (
                            snapshot.summarized_through_message_id
                        ),
                        "updated_at": snapshot.updated_at.isoformat(),
                    },
                )
            ],
            wait=True,
        )

    def get(self, conversation_id: str) -> dict[str, object] | None:
        """Read one deterministic summary point and its payload."""
        if not self._client.collection_exists(self._collection_name):
            return None
        points = self._client.retrieve(
            collection_name=self._collection_name,
            ids=[self._point_id(conversation_id)],
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            return None
        payload = points[0].payload
        if not isinstance(payload, dict):
            return None
        return payload

    def delete(self, conversation_id: str) -> None:
        """Delete the stable point; repeating the operation is safe."""
        if not self._client.collection_exists(self._collection_name):
            return
        self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.PointIdsList(
                points=[self._point_id(conversation_id)]
            ),
            wait=True,
        )

    def list_summary_payloads(self, *, limit: int = 100) -> list[dict[str, object]]:
        if limit < 1:
            raise ValueError("limit precisa ser positivo")
        if not self._client.collection_exists(self._collection_name):
            return []
        points, _ = self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="memory_type",
                        match=models.MatchValue(value="conversation_summary"),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [point.payload for point in points if isinstance(point.payload, dict)]

    def get_latest_ended(
        self, *, email: str, exclude_conversation_id: str, limit: int
    ) -> list[dict[str, object]]:
        """Return recent summary payloads; updated_at must have a payload index."""
        if not self._client.collection_exists(self._collection_name):
            return []
        self._client.create_payload_index(
            collection_name=self._collection_name,
            field_name="updated_at",
            field_schema=models.PayloadSchemaType.DATETIME,
            wait=True,
        )
        result, _ = self._client.scroll(
            collection_name=self._collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="email", match=models.MatchValue(value=email)
                    ),
                    models.FieldCondition(
                        key="memory_type",
                        match=models.MatchValue(value="conversation_summary"),
                    ),
                    models.FieldCondition(
                        key="status", match=models.MatchValue(value="ended")
                    ),
                ],
                must_not=[
                    models.FieldCondition(
                        key="conversation_id",
                        match=models.MatchValue(value=exclude_conversation_id),
                    )
                ],
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
            order_by=models.OrderBy(key="updated_at", direction=models.Direction.DESC),
        )
        return [point.payload for point in result if isinstance(point.payload, dict)]

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
