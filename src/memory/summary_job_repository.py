"""MongoDB adapter for asynchronous conversation summary jobs."""

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from pymongo.collection import Collection, ReturnDocument
from pymongo.errors import DuplicateKeyError

from .summary_jobs import SummaryJob, SummaryJobDocument, SummaryJobStatus

SUMMARY_JOBS_COLLECTION_NAME = "conversation_summary_jobs"
MAX_UNPUBLISHED_JOBS = 1_000


class SummaryJobNotFoundError(Exception):
    """Raised when a summary job does not exist."""


class MongoSummaryJobRepository:
    """Store queue metadata independently from conversation documents."""

    def __init__(self, collection: Collection[Any]) -> None:
        self._collection = collection

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("conversation_id", 1), ("closure_key", 1)],
            unique=True,
            name="conversation_closure_unique",
        )
        self._collection.create_index(
            [("status", 1), ("updated_at", 1)],
            name="summary_job_status_updated",
        )

    def create_or_get(  # noqa: PLR0913 - persistence boundary
        self,
        *,
        job_id: str,
        conversation_id: str,
        user_id: str,
        closure_key: str,
        request_id: str,
        created_at: datetime,
    ) -> tuple[SummaryJob, bool]:
        self._require_aware(created_at)
        document: SummaryJobDocument = {
            "_id": job_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "closure_key": closure_key,
            "request_id": request_id,
            "job_type": "conversation_summary",
            "status": "queued",
            "attempts": 0,
            "created_at": created_at,
            "updated_at": created_at,
            "published_at": None,
            "publication_claimed": False,
            "last_error": None,
        }
        try:
            self._collection.insert_one(document)
        except DuplicateKeyError:
            existing = self._collection.find_one(
                {
                    "conversation_id": conversation_id,
                    "closure_key": closure_key,
                    "user_id": user_id,
                }
            )
            if existing is None:
                raise
            return self._to_model(existing), False
        return self._to_model(document), True

    def mark_published(self, *, job_id: str, published_at: datetime) -> None:
        self._require_aware(published_at)
        result = self._collection.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "published_at": published_at,
                    "publication_claimed": False,
                    "updated_at": published_at,
                }
            },
        )
        if result.matched_count != 1:
            raise SummaryJobNotFoundError(job_id)

    def claim_publication(self, *, job_id: str, updated_at: datetime) -> bool:
        self._require_aware(updated_at)
        result = self._collection.update_one(
            {
                "_id": job_id,
                "status": "queued",
                "published_at": None,
                "publication_claimed": False,
            },
            {"$set": {"publication_claimed": True, "updated_at": updated_at}},
        )
        if result.modified_count == 1:
            return True
        if self._collection.find_one({"_id": job_id}) is None:
            raise SummaryJobNotFoundError(job_id)
        return False

    def release_publication(self, *, job_id: str, updated_at: datetime) -> None:
        self._require_aware(updated_at)
        result = self._collection.update_one(
            {"_id": job_id, "published_at": None},
            {"$set": {"publication_claimed": False, "updated_at": updated_at}},
        )
        if result.matched_count != 1:
            raise SummaryJobNotFoundError(job_id)

    def list_unpublished(self, *, limit: int = 100) -> list[SummaryJob]:
        if not 1 <= limit <= MAX_UNPUBLISHED_JOBS:
            raise ValueError("limit deve estar entre um e mil")
        documents = (
            self._collection.find(
                {
                    "status": "queued",
                    "published_at": None,
                    "publication_claimed": False,
                }
            )
            .sort("created_at", 1)
            .limit(limit)
        )
        return [self._to_model(document) for document in documents]

    def mark_processing(self, *, job_id: str, updated_at: datetime) -> bool:
        self._require_aware(updated_at)
        result = self._collection.update_one(
            {"_id": job_id, "status": "queued"},
            {"$set": {"status": "processing", "updated_at": updated_at}},
        )
        if result.modified_count == 1:
            return True
        if self._collection.find_one({"_id": job_id}) is None:
            raise SummaryJobNotFoundError(job_id)
        return False

    def mark_completed(self, *, job_id: str, updated_at: datetime) -> None:
        self._require_aware(updated_at)
        result = self._collection.update_one(
            {"_id": job_id, "status": "processing"},
            {"$set": {"status": "completed", "updated_at": updated_at}},
        )
        if result.matched_count != 1:
            raise SummaryJobNotFoundError(job_id)

    def mark_failed(
        self,
        *,
        job_id: str,
        updated_at: datetime,
        error: str,
        max_attempts: int,
    ) -> SummaryJobStatus:
        self._require_aware(updated_at)
        if max_attempts < 1:
            raise ValueError("max_attempts deve ser positivo")
        result = self._collection.find_one_and_update(
            {"_id": job_id, "status": "processing"},
            {
                "$inc": {"attempts": 1},
                "$set": {
                    "status": "failed",
                    "updated_at": updated_at,
                    "last_error": error[:1000],
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise SummaryJobNotFoundError(job_id)

        attempts = int(result.get("attempts", 0))
        status: SummaryJobStatus = "failed" if attempts >= max_attempts else "queued"
        if status == "queued":
            self._collection.update_one(
                {"_id": job_id},
                {"$set": {"status": "queued", "updated_at": updated_at}},
            )
        return status

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp precisa incluir timezone")

    @staticmethod
    def _to_model(document: Mapping[str, Any]) -> SummaryJob:
        created_at = MongoSummaryJobRepository._as_aware(document.get("created_at"))
        updated_at = MongoSummaryJobRepository._as_aware(document.get("updated_at"))
        published_raw = document.get("published_at")
        published_at = (
            MongoSummaryJobRepository._as_aware(published_raw)
            if published_raw is not None
            else None
        )
        return SummaryJob(
            job_id=str(document["_id"]),
            conversation_id=str(document["conversation_id"]),
            user_id=str(document["user_id"]),
            closure_key=str(document["closure_key"]),
            request_id=str(document["request_id"]),
            status=document["status"],
            attempts=int(document.get("attempts", 0)),
            created_at=created_at,
            updated_at=updated_at,
            published_at=published_at,
            publication_claimed=bool(document.get("publication_claimed", False)),
            last_error=document.get("last_error"),
        )

    @staticmethod
    def _as_aware(value: object) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("timestamp do job inválido")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
