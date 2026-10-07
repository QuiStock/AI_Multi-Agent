"""Internal conversation-closure boundary that schedules summary work durably."""

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from .mongo_repository import MongoConversationRepository
from .summary_job_repository import MongoSummaryJobRepository, SummaryJob
from .summary_queue import RedisSummaryQueue

logger = logging.getLogger(__name__)


class ConversationSummaryScheduler:
    def __init__(
        self,
        *,
        conversations: MongoConversationRepository,
        jobs: MongoSummaryJobRepository,
        queue: RedisSummaryQueue,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conversations = conversations
        self._jobs = jobs
        self._queue = queue
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def end_and_schedule(
        self,
        *,
        conversation_id: str,
        email: str,
        closure_key: str | None = None,
        request_id: str | None = None,
    ) -> SummaryJob:
        """Persist closure and job before best-effort Redis publication.

        The caller creates `closure_key` once for this internal close event and
        reuses it for any retry. Redis publication failure cannot undo the job.
        """
        now = self._clock()
        ended_at = self._conversations.mark_ended(
            conversation_id=conversation_id,
            email=email,
            ended_at=now,
        )
        stable_request_id = request_id or self.request_id_for_closure(
            conversation_id=conversation_id,
            ended_at=ended_at,
        )
        closure_key = closure_key or self.closure_key_for_request(
            conversation_id=conversation_id,
            request_id=stable_request_id,
        )
        job = self._jobs.create_or_get(
            conversation_id=conversation_id,
            email=email,
            closure_key=closure_key,
            request_id=stable_request_id,
            now=now,
        )
        if job.status == "queued" and job.published_at is None:
            try:
                self._queue.publish(job.job_id)
                self._jobs.mark_published(job_id=job.job_id, published_at=now)
            except Exception as exc:
                # Do not log exception content; the durable outbox relay retries later.
                logger.warning(
                    "Resumo agendado aguardando relay; job_id=%s error_type=%s",
                    job.job_id,
                    type(exc).__name__,
                )
        return job

    @staticmethod
    def closure_key_for_request(*, conversation_id: str, request_id: str) -> str:
        if not conversation_id.strip() or not request_id.strip():
            raise ValueError("conversation_id e request_id são obrigatórios")
        identity = json.dumps([conversation_id, request_id], separators=(",", ":"))
        return str(uuid5(NAMESPACE_URL, f"summary-close:{identity}"))

    @staticmethod
    def request_id_for_closure(*, conversation_id: str, ended_at: datetime) -> str:
        """Create a backend-stable request ID from the persisted closure time."""
        if not conversation_id.strip():
            raise ValueError("conversation_id é obrigatório")
        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("ended_at precisa incluir timezone")
        stable_timestamp = ended_at.astimezone(timezone.utc).isoformat()
        identity = json.dumps(
            [conversation_id, stable_timestamp], separators=(",", ":")
        )
        return str(uuid5(NAMESPACE_URL, f"summary-close-request:{identity}"))


class ConversationDeletionScheduler:
    """Mark an owned conversation and enqueue cross-store cleanup."""

    def __init__(
        self,
        *,
        conversations: MongoConversationRepository,
        jobs: MongoSummaryJobRepository,
        queue: RedisSummaryQueue,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conversations = conversations
        self._jobs = jobs
        self._queue = queue
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def delete_and_schedule(
        self,
        *,
        conversation_id: str,
        email: str,
        request_id: str | None = None,
    ) -> SummaryJob:
        conversation_id = conversation_id.strip()
        email = email.strip()
        if not conversation_id or not email:
            raise ValueError("conversation_id e email são obrigatórios")

        now = self._clock()
        stable_request_id = request_id or str(
            uuid5(
                NAMESPACE_URL,
                f"conversation-delete-request:{conversation_id}:{email}",
            )
        )
        marked = self._conversations.mark_deleting(
            conversation_id=conversation_id,
            email=email,
        )
        if not marked:
            existing = self._jobs.find_latest_for_conversation(
                conversation_id=conversation_id,
                email=email,
                operation="delete",
            )
            if existing is not None:
                return existing
            from .mongo_repository import ConversationNotFoundError

            raise ConversationNotFoundError(conversation_id)

        job = self._jobs.create_or_get(
            conversation_id=conversation_id,
            email=email,
            closure_key=f"delete:{stable_request_id}",
            request_id=stable_request_id,
            now=now,
            operation="delete",
        )
        if job.status == "queued" and job.published_at is None:
            try:
                self._queue.publish(job.job_id)
                self._jobs.mark_published(job_id=job.job_id, published_at=now)
            except Exception as exc:
                logger.warning(
                    "Exclusão aguardando relay; job_id=%s error_type=%s",
                    job.job_id,
                    type(exc).__name__,
                )
        return job
