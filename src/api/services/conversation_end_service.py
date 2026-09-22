from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from src.api.schemas.conversation_end import ConversationEndResponse
from src.memory.mongo_repository import MongoConversationRepository
from src.memory.summary_jobs import SummaryJobRepository
from src.memory.summary_queue import SummaryJobPublisher, SummaryQueueError


class CheckpointCleanup(Protocol):
    def delete_thread(self, thread_id: str) -> None: ...


class ConversationAlreadyEndedError(Exception):
    """Raised when a conversation already has an accepted close operation."""


class SummaryQueueUnavailableError(RuntimeError):
    """Raised when the close operation cannot publish its summary job."""


class ConversationEndService:
    def __init__(
        self,
        *,
        conversation_repository: MongoConversationRepository,
        job_repository: SummaryJobRepository,
        job_publisher: SummaryJobPublisher,
        checkpoint_cleanup: CheckpointCleanup,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conversation_repository = conversation_repository
        self._job_repository = job_repository
        self._job_publisher = job_publisher
        self._checkpoint_cleanup = checkpoint_cleanup
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def end(
        self,
        *,
        conversation_id: str,
        user_id: str,
    ) -> ConversationEndResponse:
        conversation_id = conversation_id.strip()
        user_id = user_id.strip()
        if not conversation_id or not user_id:
            raise ValueError("conversation_id e user_id são obrigatórios")

        request_id = str(uuid4())
        now = self._clock()
        ended_at = self._conversation_repository.mark_ended(
            conversation_id=conversation_id,
            user_id=user_id,
            ended_at=now,
        )
        closure_key = ended_at.isoformat()
        job, created = self._job_repository.create_or_get(
            job_id=str(uuid4()),
            conversation_id=conversation_id,
            user_id=user_id,
            closure_key=closure_key,
            request_id=request_id,
            created_at=now,
        )

        if not created and job.published_at is not None:
            raise ConversationAlreadyEndedError(conversation_id)
        if not created and job.status != "queued":
            raise ConversationAlreadyEndedError(conversation_id)

        if not self._job_repository.claim_publication(
            job_id=job.job_id,
            updated_at=self._clock(),
        ):
            raise ConversationAlreadyEndedError(conversation_id)

        self._checkpoint_cleanup.delete_thread(conversation_id)
        try:
            self._job_publisher.publish(job)
        except SummaryQueueError as exc:
            self._job_repository.release_publication(
                job_id=job.job_id,
                updated_at=self._clock(),
            )
            raise SummaryQueueUnavailableError from exc

        self._job_repository.mark_published(
            job_id=job.job_id,
            published_at=self._clock(),
        )
        return ConversationEndResponse(
            conversation_id=conversation_id,
            request_id=job.request_id,
            job_id=job.job_id,
            status="ended",
            summary_status="queued",
        )
