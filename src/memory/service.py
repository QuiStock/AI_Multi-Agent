"""Coordinate summary search, MongoDB validation, and recent-summary fallback."""

from collections.abc import Callable

from qdrant_client import QdrantClient

from .contracts import ConversationSummary, SummaryContextSelection
from .get_summary_context import get_summary_context
from .mongo_repository import MongoConversationRepository


class SummaryContextService:
    def __init__(
        self,
        *,
        repository: MongoConversationRepository,
        qdrant: QdrantClient,
        embed_query: Callable[[str], list[float]],
        collection_name: str,
        top_k: int = 3,
        min_score: float = 0.5,
        fallback_limit: int = 3,
    ) -> None:
        if not 1 <= top_k <= 3 or not 1 <= fallback_limit <= 3:
            raise ValueError("A busca e o fallback aceitam de um a três resumos")
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score deve estar entre 0.0 e 1.0")

        self._repository = repository
        self._qdrant = qdrant
        self._embed_query = embed_query
        self._collection_name = collection_name
        self._top_k = top_k
        self._min_score = min_score
        self._fallback_limit = fallback_limit

    def get_context(
        self,
        user_id: str,
        conversation_id: str,
        query: str,
    ) -> list[ConversationSummary]:
        return self.search_context(
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
        )["results"]

    def search_context(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
    ) -> SummaryContextSelection:
        """Return semantic matches or the established recent-summary fallback."""
        candidates = get_summary_context(
            user_id=user_id,
            conversation_id=conversation_id,
            query=query,
            embed_query=self._embed_query,
            qdrant=self._qdrant,
            collection_name=self._collection_name,
            limit=self._top_k,
            score_threshold=self._min_score,
        )

        relevant = [
            candidate
            for candidate in candidates
            if candidate["score"] >= self._min_score
            and candidate["conversation_id"] != conversation_id
        ]
        current_summaries = self._repository.get_ended_summaries_by_ids(
            user_id=user_id,
            conversation_ids=list(
                dict.fromkeys(candidate["conversation_id"] for candidate in relevant)
            ),
        )
        valid = [
            candidate
            for candidate in relevant
            if (current := current_summaries.get(candidate["conversation_id"]))
            is not None
            and current["summary_version"] == candidate["summary_version"]
        ]

        if valid:
            return {
                "source": "semantic",
                "results": [
                    {
                        "conversation_id": current_summaries[item["conversation_id"]][
                            "conversation_id"
                        ],
                        "title": current_summaries[item["conversation_id"]]["title"],
                        "summary": current_summaries[item["conversation_id"]][
                            "summary"
                        ],
                        "updated_at": current_summaries[item["conversation_id"]][
                            "updated_at"
                        ],
                    }
                    for item in valid
                ],
            }

        return {
            "source": "fallback",
            "results": self._repository.get_latest_ended_summaries(
                user_id=user_id,
                exclude_conversation_id=conversation_id,
                limit=self._fallback_limit,
            ),
        }
