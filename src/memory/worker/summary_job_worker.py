"""At-least-once Redis consumer backed by durable Mongo summary job state."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ..mongo_repository import ConversationNotEndedError, ConversationNotFoundError
from ..summary_job_repository import MongoSummaryJobRepository
from ..summary_jobs import SummaryJob, retry_delay_seconds
from ..summary_lock_repository import (
    ConversationSummaryLease,
    MongoConversationSummaryLockRepository,
)
from ..summary_queue import RedisSummaryQueue

logger = logging.getLogger(__name__)
MIN_LEASE_SECONDS = 3


@dataclass(frozen=True)
class SummaryJobWorkerSettings:
    worker_id: str
    clock: Callable[[], datetime] | None = None
    lease_seconds: int = 300


class SummaryProcessor(Protocol):
    def run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        before_upsert: Callable[[], None] | None = None,
    ) -> object: ...


class SummaryJobLeaseLostError(RuntimeError):
    """Raised when a worker can no longer prove ownership of its job lease."""


class SummaryJobWorker:
    def __init__(
        self,
        *,
        repository: MongoSummaryJobRepository,
        conversation_locks: MongoConversationSummaryLockRepository,
        queue: RedisSummaryQueue,
        processor: SummaryProcessor,
        settings: SummaryJobWorkerSettings,
    ) -> None:
        if not settings.worker_id.strip():
            raise ValueError("worker_id é obrigatório")
        if settings.lease_seconds < MIN_LEASE_SECONDS:
            raise ValueError("lease_seconds inválido")
        self._repository = repository
        self._conversation_locks = conversation_locks
        self._queue = queue
        self._processor = processor
        self._worker_id = settings.worker_id
        self._clock = settings.clock or (lambda: datetime.now(timezone.utc))
        self._lease_seconds = settings.lease_seconds

    def run_once(self, *, block_ms: int = 1000) -> int:
        self._queue.ensure_consumer_group()
        entries = self._queue.reclaim_pending(
            consumer=self._worker_id,
            min_idle_ms=self._lease_seconds * 1000,
        )
        if not entries:
            entries = self._queue.read_new(
                consumer=self._worker_id,
                count=10,
                block_ms=block_ms,
            )
        processed = 0
        for entry_id, job_id in entries:
            self._process_entry(entry_id=entry_id, job_id=job_id)
            processed += 1
        self._repository.mark_expired_jobs_failed(now=self._clock())
        return processed

    def run_forever(self, *, stop: threading.Event) -> None:
        self._queue.ensure_consumer_group()
        while not stop.is_set():
            try:
                self.run_once(block_ms=1000)
            except Exception as exc:
                logger.warning(
                    "Consumer de resumo falhou; error_type=%s", type(exc).__name__
                )
                stop.wait(1)

    def _process_entry(self, *, entry_id: str, job_id: str) -> None:
        job = self._claim_job(job_id)
        if job is None:
            # Duplicate signal, completed job, or a retry not due yet.
            self._queue.acknowledge(entry_id=entry_id)
            return

        lease = self._acquire_conversation_lease(job)
        if lease is None:
            self._retry_after_lock_contention(job, entry_id)
            return

        stop_heartbeat = threading.Event()
        lease_lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(job, lease, entry_id, stop_heartbeat, lease_lost),
            name=f"summary-lease-{job.job_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            self._process_claimed_job(job, lease, entry_id, lease_lost)
        except ConversationNotEndedError, ConversationNotFoundError:
            self._mark_job_superseded(job, entry_id)
        except Exception as exc:
            self._schedule_job_retry(job, entry_id, exc)
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=1)
            self._release_conversation_lease(lease)

    def _claim_job(self, job_id: str) -> SummaryJob | None:
        return self._repository.claim(
            job_id=job_id,
            worker_id=self._worker_id,
            now=self._clock(),
            lease_seconds=self._lease_seconds,
        )

    def _acquire_conversation_lease(
        self, job: SummaryJob
    ) -> ConversationSummaryLease | None:
        return self._conversation_locks.acquire(
            conversation_id=job.conversation_id,
            owner=self._worker_id,
            now=self._clock(),
            lease_seconds=self._lease_seconds,
        )

    def _process_claimed_job(
        self,
        job: SummaryJob,
        lease: ConversationSummaryLease,
        entry_id: str,
        lease_lost: threading.Event,
    ) -> None:
        def validate_lease_before_upsert() -> None:
            if lease_lost.is_set() or not self._renew(job, lease):
                lease_lost.set()
                raise SummaryJobLeaseLostError("summary_job_lease_lost")

        self._processor.run(
            user_id=job.user_id,
            conversation_id=job.conversation_id,
            before_upsert=validate_lease_before_upsert,
        )
        if lease_lost.is_set():
            raise SummaryJobLeaseLostError("summary_job_lease_lost")
        completed = self._repository.complete(
            job_id=job.job_id,
            worker_id=self._worker_id,
            now=self._clock(),
        )
        if completed:
            self._queue.acknowledge(entry_id=entry_id)

    def _retry_after_lock_contention(self, job: SummaryJob, entry_id: str) -> None:
        status = self._repository.schedule_retry(
            job=job,
            worker_id=self._worker_id,
            now=self._clock(),
            delay_seconds=retry_delay_seconds(job.attempts),
            safe_error_code="conversation_lock_busy",
        )
        if status in {"queued", "failed"}:
            self._queue.acknowledge(entry_id=entry_id)

    def _mark_job_superseded(self, job: SummaryJob, entry_id: str) -> None:
        superseded = self._repository.mark_superseded(
            job_id=job.job_id,
            worker_id=self._worker_id,
            now=self._clock(),
        )
        if superseded:
            self._queue.acknowledge(entry_id=entry_id)

    def _schedule_job_retry(
        self, job: SummaryJob, entry_id: str, error: Exception
    ) -> None:
        status = self._repository.schedule_retry(
            job=job,
            worker_id=self._worker_id,
            now=self._clock(),
            delay_seconds=retry_delay_seconds(job.attempts, max_seconds=300),
            safe_error_code=type(error).__name__,
        )
        if status in {"queued", "failed"}:
            self._queue.acknowledge(entry_id=entry_id)
        logger.warning(
            "Job de resumo terminou com falha; job_id=%s state=%s error_type=%s",
            job.job_id,
            status,
            type(error).__name__,
        )

    def _release_conversation_lease(self, lease: ConversationSummaryLease) -> None:
        try:
            self._conversation_locks.release(lease=lease, now=self._clock())
        except Exception as exc:
            logger.warning(
                "Lease de resumo expirará naturalmente; error_type=%s",
                type(exc).__name__,
            )

    def _heartbeat(
        self,
        job: SummaryJob,
        lease: ConversationSummaryLease,
        entry_id: str,
        stop: threading.Event,
        lease_lost: threading.Event,
    ) -> None:
        interval = max(1, self._lease_seconds // 3)
        while not stop.wait(interval):
            if not self._renew(job, lease) or not self._queue.refresh_pending(
                entry_id=entry_id,
                consumer=self._worker_id,
            ):
                lease_lost.set()
                return

    def _renew(self, job: SummaryJob, lease: ConversationSummaryLease) -> bool:
        job_renewed = self._repository.renew_lease(
            job_id=job.job_id,
            worker_id=self._worker_id,
            now=self._clock(),
            lease_seconds=self._lease_seconds,
        )
        lock_renewed = self._conversation_locks.renew(
            lease=lease,
            now=self._clock(),
            lease_seconds=self._lease_seconds,
        )
        return job_renewed and lock_renewed
