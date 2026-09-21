"""Retrieve summary candidates from the user's Qdrant memory collection."""

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, cast

from qdrant_client import QdrantClient, models

from .contracts import MAX_SUMMARY_RESULTS, SummaryCandidate, SummarySearchRequest


def _as_timestamp(value: object) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return None


def _validate_request(request: SummarySearchRequest) -> None:
    required = {
        "user_id": request.user_id,
        "conversation_id": request.conversation_id,
        "query": request.query,
        "collection_name": request.collection_name,
    }
    if any(not value.strip() for value in required.values()):
        raise ValueError(
            "user_id, conversation_id, query e collection_name são obrigatórios"
        )
    if not 1 <= request.limit <= MAX_SUMMARY_RESULTS:
        raise ValueError("limit deve estar entre um e três")
    if not 0.0 <= request.score_threshold <= 1.0:
        raise ValueError("score_threshold deve estar entre 0.0 e 1.0")


def _summary_filter(request: SummarySearchRequest) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=request.user_id),
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
                match=models.MatchValue(value=request.conversation_id),
            ),
        ],
    )


def _has_valid_identity(payload: Mapping[str, Any], user_id: str) -> bool:
    conversation_id = payload.get("conversation_id")
    return (
        isinstance(conversation_id, str)
        and bool(conversation_id.strip())
        and payload.get("user_id") == user_id
        and payload.get("memory_type") == "conversation_summary"
        and payload.get("status") == "ended"
    )


def _has_valid_summary(payload: Mapping[str, Any]) -> bool:
    title = payload.get("title")
    summary = payload.get("summary")
    version = payload.get("summary_version")
    return (
        (title is None or isinstance(title, str))
        and isinstance(summary, str)
        and bool(summary.strip())
        and isinstance(version, int)
        and not isinstance(version, bool)
        and version >= 1
    )


def _candidate_from_point(
    point: Any,
    *,
    user_id: str,
) -> SummaryCandidate | None:
    payload = point.payload
    if not isinstance(payload, Mapping):
        return None
    if not _has_valid_identity(payload, user_id) or not _has_valid_summary(payload):
        return None

    updated_at = _as_timestamp(payload.get("updated_at"))
    if updated_at is None:
        return None

    return {
        "conversation_id": cast(str, payload["conversation_id"]),
        "title": cast(str | None, payload.get("title")),
        "summary": cast(str, payload["summary"]),
        "updated_at": updated_at,
        "summary_version": cast(int, payload["summary_version"]),
        "score": float(point.score),
    }


def get_summary_context(
    *,
    request: SummarySearchRequest,
    embed_query: Callable[[str], list[float]],
    qdrant: QdrantClient,
) -> list[SummaryCandidate]:
    """Return ranked, well-formed Qdrant payloads; score validation is in service."""
    _validate_request(request)
    result = qdrant.query_points(
        collection_name=request.collection_name,
        query=embed_query(request.query),
        query_filter=_summary_filter(request),
        limit=request.limit,
        score_threshold=request.score_threshold,
        with_payload=True,
    )

    candidates = []
    for point in result.points:
        candidate = _candidate_from_point(point, user_id=request.user_id)
        if candidate is not None:
            candidates.append(candidate)
    return candidates
