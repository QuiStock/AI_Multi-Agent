"""Coordinate summary search, MongoDB validation, and recent-summary fallback."""

from collections.abc import Callable
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from .contracts import (
    MAX_SUMMARY_RESULTS,
    ConversationSummary,
    SummaryContextSelection,
    SummarySearchRequest,
)
from .get_summary_context import get_summary_context
from .mongo_repository import MongoConversationRepository


@dataclass(frozen=True, slots=True)
class SummarySearchConfig:
    """Limits and collection settings for semantic summary retrieval."""

    collection_name: str
    top_k: int = MAX_SUMMARY_RESULTS
    min_score: float = 0.5
    fallback_limit: int = MAX_SUMMARY_RESULTS

    def __post_init__(self) -> None:
        if not self.collection_name.strip():
            raise ValueError("collection_name é obrigatório")
        if (
            not 1 <= self.top_k <= MAX_SUMMARY_RESULTS
            or not 1 <= self.fallback_limit <= MAX_SUMMARY_RESULTS
        ):
            raise ValueError("A busca e o fallback aceitam de um a três resumos")
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("min_score deve estar entre 0.0 e 1.0")


class SummaryContextService:
    def __init__(
        self,
        repository: MongoConversationRepository,
        qdrant: QdrantClient,
        embed_query: Callable[[str], list[float]],
        search_config: SummarySearchConfig,
    ) -> None:
        self._repository = repository
        self._qdrant = qdrant
        self._embed_query = embed_query
        self._search_config = search_config

    def get_context(
        self,
        email: str,
        conversation_id: str,
        query: str,
    ) -> list[ConversationSummary]:
        return self.search_context(
            email=email,
            conversation_id=conversation_id,
            query=query,
        )["results"]

    def search_context(
        self,
        *,
        email: str,
        conversation_id: str,
        query: str,
    ) -> SummaryContextSelection:
        """Return semantic matches or the established recent-summary fallback."""
        candidates = get_summary_context(
            request=SummarySearchRequest(
                email=email,
                conversation_id=conversation_id,
                query=query,
                collection_name=self._search_config.collection_name,
                limit=self._search_config.top_k,
                score_threshold=self._search_config.min_score,
            ),
            embed_query=self._embed_query,
            qdrant=self._qdrant,
        )

        relevant = [
            candidate
            for candidate in candidates
            if candidate["score"] >= self._search_config.min_score
            and candidate["conversation_id"] != conversation_id
        ]
        current_summaries = self._repository.get_ended_conversation_metadata_by_ids(
            email=email,
            conversation_ids=list(
                dict.fromkeys(candidate["conversation_id"] for candidate in relevant)
            ),
        )
        valid = [
            candidate
            for candidate in relevant
            if current_summaries.get(candidate["conversation_id"]) is not None
        ]

        if valid:
            return {
                "source": "semantic",
                "results": [
                    {
                        "conversation_id": item["conversation_id"],
                        "title": current_summaries[item["conversation_id"]]["title"],
                        "summary": item["summary"],
                        "updated_at": item["updated_at"],
                    }
                    for item in valid
                ],
            }

        return {
            "source": "fallback",
            "results": self._recent_qdrant_summaries(
                email=email, exclude_conversation_id=conversation_id
            ),
        }

    def _recent_qdrant_summaries(
        self, *, email: str, exclude_conversation_id: str
    ) -> list[ConversationSummary]:
        """Fallback uses Qdrant payload text; Mongo is only an owner/status gate."""
        if not self._qdrant.collection_exists(self._search_config.collection_name):
            return []
        self._qdrant.create_payload_index(
            collection_name=self._search_config.collection_name,
            field_name="updated_at",
            field_schema=models.PayloadSchemaType.DATETIME,
            wait=True,
        )
        points, _ = self._qdrant.scroll(
            collection_name=self._search_config.collection_name,
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
            limit=self._search_config.fallback_limit,
            with_payload=True,
            with_vectors=False,
            order_by=models.OrderBy(key="updated_at", direction=models.Direction.DESC),
        )
        candidates = [
            point.payload
            for point in points
            if isinstance(point.payload, dict)
            and isinstance(point.payload.get("conversation_id"), str)
            and isinstance(point.payload.get("summary"), str)
            and point.payload.get("summary", "").strip()
        ]
        metadata = self._repository.get_ended_conversation_metadata_by_ids(
            email=email,
            conversation_ids=[str(item["conversation_id"]) for item in candidates],
        )
        return [
            {
                "conversation_id": str(item["conversation_id"]),
                "title": metadata[str(item["conversation_id"])]["title"],
                "summary": str(item["summary"]),
                "updated_at": str(item["updated_at"]),
            }
            for item in candidates
            if str(item["conversation_id"]) in metadata
        ]
