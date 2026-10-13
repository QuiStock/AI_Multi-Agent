"""Coordinate semantic summary search and MongoDB ownership validation."""

from collections.abc import Callable
from dataclasses import dataclass

from qdrant_client import QdrantClient

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

    def __post_init__(self) -> None:
        if not self.collection_name.strip():
            raise ValueError("collection_name é obrigatório")
        if not 1 <= self.top_k <= MAX_SUMMARY_RESULTS:
            raise ValueError("A busca aceita de um a três resumos")
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
        """Return only relevant summaries belonging to this user."""
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

        return {"source": "none", "results": []}
