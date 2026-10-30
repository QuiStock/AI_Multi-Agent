"""Coordinate authenticated, Qdrant-only conversation-summary recovery."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
from .qdrant_summary_indexer import ensure_summary_payload_indexes


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
    ) -> None:
        # Kept as a compatibility slot for callers that used to pass Mongo.
        # Search never consults it: Qdrant payloads are the recovery source.
        self._repository = repository
        self._qdrant = qdrant
        self._embed_query = embed_query
        self._search_config = search_config
        self._payload_indexes_ready = False

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
        start_date: date | None = None,
        end_date: date | None = None,
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
        if (start_date is None) != (end_date is None):
            raise ValueError("start_date e end_date devem ser informados juntos")
        if (
            start_date is not None
            and end_date is not None
            and start_date > end_date
        ):
            raise ValueError("start_date deve ser anterior ou igual a end_date")
        if hasattr(
            self._qdrant, "collection_exists"
        ) and not self._qdrant.collection_exists(self._search_config.collection_name):
            return {"source": "none", "results": []}
        if not self._payload_indexes_ready:
            ensure_summary_payload_indexes(
                self._qdrant,
                self._search_config.collection_name,
            )
            self._payload_indexes_ready = True

        if start_date is not None and end_date is not None:
            zone = ZoneInfo(self._search_config.timezone_name)
            start = datetime.combine(start_date, time.min, tzinfo=zone)
            end = datetime.combine(
                end_date + timedelta(days=1), time.min, tzinfo=zone
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
