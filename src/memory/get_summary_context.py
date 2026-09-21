"""Retrieve summary candidates from the user's Qdrant memory collection."""

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient, models

from .contracts import SummaryCandidate


def _as_timestamp(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return None


def get_summary_context(
    *,
    user_id: str,
    conversation_id: str,
    query: str,
    embed_query: Callable[[str], list[float]],
    qdrant: QdrantClient,
    collection_name: str,
    limit: int = 3,
    score_threshold: float = 0.5,
) -> list[SummaryCandidate]:
    """Return ranked, well-formed Qdrant payloads; score validation is in service."""
    if not user_id.strip():
        raise ValueError("user_id é obrigatório")
    if not conversation_id.strip():
        raise ValueError("conversation_id é obrigatório")
    if not query.strip():
        raise ValueError("query é obrigatória")
    if not collection_name.strip():
        raise ValueError("collection_name é obrigatório")
    if not 1 <= limit <= 3:
        raise ValueError("limit deve estar entre um e três")
    if not 0.0 <= score_threshold <= 1.0:
        raise ValueError("score_threshold deve estar entre 0.0 e 1.0")

    result = qdrant.query_points(
        collection_name=collection_name,
        query=embed_query(query),
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id),
                ),
                models.FieldCondition(
                    key="memory_type",
                    match=models.MatchValue(value="conversation_summary"),
                ),
                models.FieldCondition(
                    key="status",
                    match=models.MatchValue(value="ended"),
                ),
            ],
            must_not=[
                models.FieldCondition(
                    key="conversation_id",
                    match=models.MatchValue(value=conversation_id),
                ),
            ],
        ),
        limit=limit,
        score_threshold=score_threshold,
        with_payload=True,
    )

    candidates: list[SummaryCandidate] = []
    for point in result.points:
        payload: Any = point.payload
        if not isinstance(payload, Mapping):
            continue

        candidate_id = payload.get("conversation_id")
        candidate_user_id = payload.get("user_id")
        memory_type = payload.get("memory_type")
        status = payload.get("status")
        title = payload.get("title")
        summary = payload.get("summary")
        version = payload.get("summary_version")
        updated_at = _as_timestamp(payload.get("updated_at"))

        if not isinstance(candidate_id, str) or not candidate_id.strip():
            continue
        if candidate_user_id != user_id:
            continue
        if memory_type != "conversation_summary" or status != "ended":
            continue
        if title is not None and not isinstance(title, str):
            continue
        if not isinstance(summary, str) or not summary.strip():
            continue
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            continue
        if updated_at is None:
            continue

        candidates.append(
            {
                "conversation_id": candidate_id,
                "title": title,
                "summary": summary,
                "updated_at": updated_at,
                "summary_version": version,
                "score": float(point.score),
            }
        )

    return candidates
