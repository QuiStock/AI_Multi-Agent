"""MongoDB repository for durable, content-free summary job metadata."""

import json
import re
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import ASCENDING, ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

SUMMARY_JOBS_COLLECTION_NAME = "conversation_summary_jobs"
SummaryJobStatus = Literal["queued", "processing", "completed", "failed", "superseded"]
SummaryJobOperation = Literal["summary", "delete"]
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_BASE_SECONDS = 2
DEFAULT_RETRY_MAX_SECONDS = 300


class SummaryJob(BaseModel):
    """Durable job metadata; transcripts and generated summaries are excluded."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    email: str = Field(min_length=1)
    closure_key: str = Field(min_length=1)
    request_id: str | None = None
    operation: SummaryJobOperation = "summary"
    status: SummaryJobStatus = "queued"
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=DEFAULT_MAX_ATTEMPTS, ge=1)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    next_attempt_at: datetime | None = None
    lease_owner: str | None = None
    lease_until: datetime | None = None
    last_error: str | None = None

    @field_validator(
        "created_at", "updated_at", "published_at", "next_attempt_at", "lease_until"
    )
    @classmethod
    def require_aware_datetimes(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Datas do job precisam incluir timezone")
        return value


def retry_delay_seconds(
    attempts: int,
    *,
    base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
    max_seconds: int = DEFAULT_RETRY_MAX_SECONDS,
) -> int:
    """Return bounded exponential backoff for a one-based attempt count."""
    if attempts < 1:
        raise ValueError("attempts precisa ser pelo menos 1")
    if base_seconds < 1 or max_seconds < base_seconds:
        raise ValueError("Configuração de backoff inválida")
    delay = base_seconds * (1 << (attempts - 1))
    return delay if delay < max_seconds else max_seconds


class MongoSummaryJobRepository:
    def __init__(
        self,
        collection: Collection,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts precisa ser positivo")
        self._collection = collection
        self._max_attempts = max_attempts
        self._indexes_ready = False

    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("conversation_id", ASCENDING), ("closure_key", ASCENDING)],
            unique=True,
            name="uq_summary_job_conversation_closure",
        )
        self._collection.create_index(
            [
                ("status", ASCENDING),
                ("next_attempt_at", ASCENDING),
                ("created_at", ASCENDING),
            ],
            name="ix_summary_job_due",
        )
        self._collection.create_index(
            [("status", ASCENDING), ("lease_until", ASCENDING)],
            name="ix_summary_job_expired_lease",
        )
        self._indexes_ready = True

    def create_or_get(
        self,
        *,
        conversation_id: str,
        email: str,
        closure_key: str,
        request_id: str | None,
        now: datetime,
        operation: SummaryJobOperation = "summary",
    ) -> SummaryJob:
        if not self._indexes_ready:
            self.ensure_indexes()
        self._validate_key(conversation_id, "conversation_id")
        self._validate_key(email, "email")
        self._validate_key(closure_key, "closure_key")
        self._require_aware(now)
        identity = json.dumps([conversation_id, closure_key], separators=(",", ":"))
        job_id = str(uuid5(NAMESPACE_URL, f"summary-job:{operation}:{identity}"))
        document = {
            "_id": job_id,
            "conversation_id": conversation_id,
            "email": email,
            "closure_key": closure_key,
            "request_id": request_id,
            "operation": operation,
            "status": "queued",
            "attempts": 0,
            "max_attempts": self._max_attempts,
            "created_at": now,
            "updated_at": now,
            "published_at": None,
            "next_attempt_at": now,
            "lease_owner": None,
            "lease_until": None,
            "last_error": None,
        }
        with suppress(DuplicateKeyError):
            self._collection.update_one(
                {"conversation_id": conversation_id, "closure_key": closure_key},
                {"$setOnInsert": document},
                upsert=True,
            )
        # Concurrent retries can race the unique-index upsert; read the winner.
        stored = self._collection.find_one(
            {"conversation_id": conversation_id, "closure_key": closure_key}
        )
        if stored is None:
            raise RuntimeError("Job de resumo não foi persistido")
        if stored.get("email") != email:
            raise ValueError("A chave de encerramento já pertence a outro usuário")
        return self._parse(stored)

    def find_unpublished(self, *, now: datetime, limit: int = 100) -> list[SummaryJob]:
        if not self._indexes_ready:
            self.ensure_indexes()
        self._require_aware(now)
        cursor = (
            self._collection.find(
                {
                    "status": "queued",
                    "$and": [
                        {
                            "$or": [
                                {"published_at": None},
                                {"published_at": {"$exists": False}},
                            ]
                        },
                        {
                            "$or": [
                                {"next_attempt_at": None},
                                {"next_attempt_at": {"$lte": now}},
                            ]
                        },
                    ],
                }
            )
            .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
            .limit(limit)
        )
        return [self._parse(item) for item in cursor]

    def find_latest_for_conversation(
        self,
        *,
        conversation_id: str,
        email: str,
        operation: SummaryJobOperation,
    ) -> SummaryJob | None:
        document = self._collection.find_one(
            {
                "conversation_id": conversation_id,
                "email": email,
                "operation": operation,
            },
            sort=[("updated_at", -1), ("_id", -1)],
        )
        return self._parse(document) if document is not None else None

    def mark_published(self, *, job_id: str, published_at: datetime) -> bool:
        self._require_aware(published_at)
        result = self._collection.update_one(
            {"_id": job_id, "status": "queued"},
            {"$set": {"published_at": published_at, "updated_at": published_at}},
        )
        return result.matched_count == 1

    def claim(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        lease_seconds: int = 300,
    ) -> SummaryJob | None:
        self._require_aware(now)
        self._validate_key(worker_id, "worker_id")
        if lease_seconds < 1:
            raise ValueError("lease_seconds precisa ser positivo")
        query = {
            "_id": job_id,
            "attempts": {"$lt": self._max_attempts},
            "$and": [
                {
                    "$or": [
                        {"status": "queued"},
                        {"status": "processing", "lease_until": {"$lte": now}},
                    ]
                },
                {
                    "$or": [
                        {"next_attempt_at": None},
                        {"next_attempt_at": {"$lte": now}},
                    ]
                },
            ],
        }
        claimed = self._collection.find_one_and_update(
            query,
            {
                "$set": {
                    "status": "processing",
                    "lease_owner": worker_id,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                },
                "$inc": {"attempts": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._parse(claimed) if claimed is not None else None

    def complete(self, *, job_id: str, worker_id: str, now: datetime) -> bool:
        self._require_aware(now)
        result = self._collection.update_one(
            {"_id": job_id, "status": "processing", "lease_owner": worker_id},
            {
                "$set": {"status": "completed", "updated_at": now},
                "$unset": {"lease_owner": "", "lease_until": "", "last_error": ""},
            },
        )
        return result.modified_count == 1

    def mark_superseded(self, *, job_id: str, worker_id: str, now: datetime) -> bool:
        self._require_aware(now)
        result = self._collection.update_one(
            {"_id": job_id, "status": "processing", "lease_owner": worker_id},
            {
                "$set": {
                    "status": "superseded",
                    "updated_at": now,
                    "last_error": "conversation_not_ended_or_missing",
                },
                "$unset": {"lease_owner": "", "lease_until": ""},
            },
        )
        return result.modified_count == 1

    def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        lease_seconds: int = 300,
    ) -> bool:
        self._require_aware(now)
        result = self._collection.update_one(
            {
                "_id": job_id,
                "status": "processing",
                "lease_owner": worker_id,
                "lease_until": {"$gt": now},
            },
            {
                "$set": {
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "updated_at": now,
                }
            },
        )
        return result.matched_count == 1

    def schedule_retry(
        self,
        *,
        job: SummaryJob,
        worker_id: str,
        now: datetime,
        delay_seconds: int,
        safe_error_code: str,
    ) -> str:
        self._require_aware(now)
        if delay_seconds < 0:
            raise ValueError("delay_seconds não pode ser negativo")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", safe_error_code):
            raise ValueError("safe_error_code deve ser um código técnico simples")
        status = "failed" if job.attempts >= job.max_attempts else "queued"
        values: dict[str, Any] = {
            "status": status,
            "updated_at": now,
            "last_error": safe_error_code,
        }
        if status == "queued":
            values["next_attempt_at"] = now + timedelta(seconds=delay_seconds)
            values["published_at"] = None
        result = self._collection.update_one(
            {"_id": job.job_id, "status": "processing", "lease_owner": worker_id},
            {
                "$set": values,
                "$unset": {"lease_owner": "", "lease_until": ""},
            },
        )
        return status if result.modified_count == 1 else "lease_lost"

    def requeue_failed(self, *, job_id: str, now: datetime) -> bool:
        self._require_aware(now)
        result = self._collection.update_one(
            {"_id": job_id, "status": "failed"},
            {
                "$set": {
                    "status": "queued",
                    "attempts": 0,
                    "next_attempt_at": now,
                    "published_at": None,
                    "updated_at": now,
                },
                "$unset": {"last_error": ""},
            },
        )
        return result.modified_count == 1

    def mark_expired_jobs_failed(self, *, now: datetime) -> int:
        self._require_aware(now)
        result = self._collection.update_many(
            {
                "status": "processing",
                "attempts": {"$gte": self._max_attempts},
                "lease_until": {"$lte": now},
            },
            {
                "$set": {
                    "status": "failed",
                    "updated_at": now,
                    "last_error": "lease_exhausted",
                },
                "$unset": {"lease_owner": "", "lease_until": ""},
            },
        )
        return result.modified_count

    @staticmethod
    def _parse(document: dict[str, Any]) -> SummaryJob:
        values = dict(document)
        values["job_id"] = values.pop("_id")
        for field in (
            "created_at",
            "updated_at",
            "published_at",
            "next_attempt_at",
            "lease_until",
        ):
            value = values.get(field)
            if isinstance(value, datetime) and value.tzinfo is None:
                values[field] = value.replace(tzinfo=timezone.utc)
        return SummaryJob.model_validate(values)

    @staticmethod
    def _validate_key(value: str, field: str) -> None:
        if not value.strip():
            raise ValueError(f"{field} é obrigatório")

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp precisa incluir timezone")
