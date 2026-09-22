from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from src.memory.summary_job_repository import MongoSummaryJobRepository


def _created_at() -> datetime:
    return datetime(2026, 9, 22, 17, 30, tzinfo=timezone.utc)


def _document() -> dict[str, object]:
    timestamp = _created_at()
    return {
        "_id": "job-1",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "closure_key": timestamp.isoformat(),
        "request_id": "request-1",
        "job_type": "conversation_summary",
        "status": "queued",
        "attempts": 0,
        "created_at": timestamp,
        "updated_at": timestamp,
        "published_at": None,
        "publication_claimed": False,
        "last_error": None,
    }


def test_create_job_persists_metadata_outside_conversation_document() -> None:
    collection = Mock()
    repository = MongoSummaryJobRepository(collection)

    job, created = repository.create_or_get(
        job_id="job-1",
        conversation_id="conversation-1",
        user_id="user-1",
        closure_key="2026-09-22T17:30:00+00:00",
        request_id="request-1",
        created_at=_created_at(),
    )

    assert created is True
    assert job.status == "queued"
    document = collection.insert_one.call_args.args[0]
    assert document["job_type"] == "conversation_summary"
    assert document["conversation_id"] == "conversation-1"


def test_duplicate_closure_returns_existing_job() -> None:
    collection = Mock()
    collection.insert_one.side_effect = Exception()
    collection.find_one.return_value = _document()
    repository = MongoSummaryJobRepository(collection)

    # DuplicateKeyError is intentionally supplied by the adapter boundary in
    # production; this test uses the concrete exception below.
    from pymongo.errors import DuplicateKeyError

    collection.insert_one.side_effect = DuplicateKeyError("duplicate")
    job, created = repository.create_or_get(
        job_id="job-2",
        conversation_id="conversation-1",
        user_id="user-1",
        closure_key="2026-09-22T17:30:00+00:00",
        request_id="request-2",
        created_at=_created_at(),
    )

    assert created is False
    assert job.job_id == "job-1"


def test_mark_processing_is_compare_and_set() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(modified_count=1)
    repository = MongoSummaryJobRepository(collection)

    claimed = repository.mark_processing(job_id="job-1", updated_at=_created_at())

    assert claimed is True
    assert collection.update_one.call_args.args[0] == {
        "_id": "job-1",
        "status": "queued",
    }


def test_claim_publication_allows_only_one_publisher() -> None:
    collection = Mock()
    collection.update_one.return_value = SimpleNamespace(modified_count=1)
    repository = MongoSummaryJobRepository(collection)

    claimed = repository.claim_publication(
        job_id="job-1",
        updated_at=_created_at(),
    )

    assert claimed is True
    assert collection.update_one.call_args.args[0] == {
        "_id": "job-1",
        "status": "queued",
        "published_at": None,
        "publication_claimed": False,
    }
