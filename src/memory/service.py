"""Coordinate authenticated, Qdrant-only conversation-summary recovery."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from qdrant_client import QdrantClient

from .contracts import (
    MAX_SUMMARY_RESULTS,
    ConversationSummary,
    SummaryContextSelection,
    SummarySearchRequest,
)
from .get_summary_context import (
    get_recent_summary_context,
    get_summary_context,
    get_temporal_summary_context,
)


@dataclass(frozen=True, slots=True)
class SummarySearchConfig:
    """Limits and collection settings for semantic summary retrieval."""

    collection_name: str
    top_k: int = MAX_SUMMARY_RESULTS
    min_score: float = 0.5
    timezone_name: str = "America/Sao_Paulo"

    def __post_init__(self) -> None:
        if not self.collection_name.strip():
            raise ValueError("collection_name é obrigatório")
        if not 1 <= self.top_k <= MAX_SUMMARY_RESULTS:
            raise ValueError("A busca aceita de um a três resumos")
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("min_score deve estar entre 0.0 e 1.0")
        ZoneInfo(self.timezone_name)


class SummaryContextService:
    def __init__(
        self,
        repository: object | None,
        qdrant: QdrantClient,
        embed_query: Callable[[str], list[float]],
        search_config: SummarySearchConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # Kept as a compatibility slot for callers that used to pass Mongo.
        # Search never consults it: Qdrant payloads are the recovery source.
        self._repository = repository
        self._qdrant = qdrant
        self._embed_query = embed_query
        self._search_config = search_config
        self._clock = clock or (lambda: datetime.now(UTC))

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
        """Return temporal, semantic, recent-fallback, or empty context."""
        request = SummarySearchRequest(
            email=email,
            conversation_id=conversation_id,
            query=query,
            collection_name=self._search_config.collection_name,
            limit=self._search_config.top_k,
            score_threshold=self._search_config.min_score,
        )
        if hasattr(
            self._qdrant, "collection_exists"
        ) and not self._qdrant.collection_exists(self._search_config.collection_name):
            return {"source": "none", "results": []}

        if _mentions_yesterday(query):
            start, end = _previous_civil_day(
                self._clock(), self._search_config.timezone_name
            )
            candidates = get_temporal_summary_context(
                request=request,
                start=start,
                end=end,
                qdrant=self._qdrant,
            )
            return {
                "source": "temporal" if candidates else "none",
                "results": _as_summaries(candidates),
            }

        candidates = get_summary_context(
            request=request,
            embed_query=self._embed_query,
            qdrant=self._qdrant,
        )
        relevant = [
            candidate
            for candidate in candidates
            if candidate["score"] >= self._search_config.min_score
        ]
        if relevant:
            return {"source": "semantic", "results": _as_summaries(relevant)}

        recent = get_recent_summary_context(request=request, qdrant=self._qdrant)
        return {
            "source": "recent_fallback" if recent else "none",
            "results": _as_summaries(recent),
        }


def _as_summaries(
    candidates: Sequence[Mapping[str, object]],
) -> list[ConversationSummary]:
    summaries: list[ConversationSummary] = []
    for item in candidates:
        conversation_id = item.get("conversation_id")
        summary_text = item.get("summary")
        updated_at = item.get("updated_at")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            continue
        if not isinstance(summary_text, str) or not summary_text.strip():
            continue
        if not isinstance(updated_at, str) or not updated_at.strip():
            continue
        title = item.get("title")
        summary: ConversationSummary = {
            "conversation_id": conversation_id,
            "title": title if isinstance(title, str) else None,
            "summary": summary_text,
            "updated_at": updated_at,
        }
        summaries.append(summary)
    return summaries[:MAX_SUMMARY_RESULTS]


def _mentions_yesterday(query: str) -> bool:
    normalized = " ".join(query.casefold().split())
    return "ontem" in normalized


def _previous_civil_day(now: datetime, timezone_name: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1), today
